import asyncio
import logging
import sys
import uuid
import os
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

from engine.db import DatabaseManager
from engine.models import Project, Plan, Task, ExecutionPhase, AssignedRole, TaskEvent, MessageType
from engine.orchestrator import Orchestrator
from engine.scheduler import Scheduler
from engine.transport.internal_transport import InternalTransport
from engine.services.execution import ExecutionService
from engine.services.sandbox import LocalPythonSandbox
from engine.services.artifact_store import ArtifactStore
from engine.services.verification_service import VerificationService
from engine.providers.nvidia_provider import NvidiaProvider
from workers.planner import PlannerWorker
from workers.executor import ExecutionWorker

# Logging setup for forensics
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler("run_9_1_forensics.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("RUN_9_1")

async def setup_initial_state(db_manager: DatabaseManager):
    async with db_manager.session_scope() as session:
        project = Project(
            name="Run 9.1 - Snake Game",
            created_at=datetime.now(timezone.utc)
        )
        session.add(project)
        await session.flush()

        plan = Plan(
            project_id=project.id,
            version=1,
            name="Initial Plan",
            status="IN_PROGRESS",
            created_at=datetime.now(timezone.utc)
        )
        session.add(plan)
        await session.flush()

        project.active_plan_id = plan.id
        
        task = Task(
            id=str(uuid.uuid4()),
            plan_id=plan.id,
            assigned_role=AssignedRole.PLANNER.value,
            execution_phase=ExecutionPhase.PLANNING.value,
            state="READY",
            state_revision=0,
            attempt_count=0,
            expected_artifacts=[],
            acceptance_criteria=[],
            updated_at=datetime.now(timezone.utc)
        )
        session.add(task)
        await session.flush()
        
        logger.info(f"Setup complete. Project: {project.id}, Plan: {plan.id}, Task: {task.id}")
        return project.id, plan.id, task.id

async def main():
    prompt = (
        "Erstelle eine vollständige, spielbare Implementierung des klassischen Spiels 'Snake' für den Webbrowser. "
        "Das Spiel soll in einer einzigen Datei (index.html) oder einer kleinen, klar strukturierten Gruppe von Dateien realisiert werden. "
        "\n\nFunktionale Anforderungen:\n"
        "1. Spiellogik: Die Schlange muss sich kontinuierlich bewegen, Steuerung via Pfeiltasten/WASD, Futter an Zufallspositionen, Wachstum beim Fressen.\n"
        "2. Kollisionsabfrage: Ende bei Wandberührung oder Selbstkollision.\n"
        "3. UI: Sichtbares Spielfeld (Canvas), Echtzeit-Score-Anzeige, Game-Over-Bildschirm mit Score und Restart-Button.\n"
        "4. Visuelles Design: Modernes, dunkles Design via CSS.\n"
        "\nTechnische Anforderungen:\n"
        "- Technologie: HTML5, CSS3, Vanilla JavaScript (keine Frameworks).\n"
        "- Struktur: Sauber kommentiert, Trennung von Game-Loop, Input und Rendering.\n"
        "- Akzeptanzkriterium: Vorhandensein einer funktionierenden index.html."
    )
    
    # Setup Database
    db_path = "firma_run_9_1_final_test.db"
    if os.path.exists(db_path):
        logger.info(f"Cleaning up old database: {db_path}")
        os.remove(db_path)
        
    db_manager = DatabaseManager(f"sqlite+aiosqlite:///{db_path}")
    await db_manager.initialize_db()
    from engine.models import Base
    await db_manager.create_tables(Base)

    # Setup Services
    sandbox = LocalPythonSandbox()
    artifact_store = ArtifactStore()
    verification_service = VerificationService(sandbox)
    execution_service = ExecutionService(sandbox)
    
    # --- CUSTOM VERIFICATION FOR WEB PROJECT ---
    async def verify_snake_game(*args, **kwargs):
        print("DEBUG: verify_snake_game called!")
        # Extract arguments from args and kwargs
        # The Orchestrator calls: verify(session, task_id=..., project_id=..., plan_version=...)
        session = args[0] if len(args) > 0 else kwargs.get("session")
        task_id = kwargs.get("task_id") or (args[1] if len(args) > 1 else None)
        project_id = kwargs.get("project_id") or (args[2] if len(args) > 2 else None)
        plan_version = kwargs.get("plan_version") or (args[3] if len(args) > 3 else None)
        
        logger.info(f"[CustomVerify] Verifying Snake Game for task {task_id}")
        # Fetch artifacts from store
        artifacts = await artifact_store.get_artifacts(session, project_id, plan_version, task_id)
        
        if not artifacts:
            return TaskEvent.VERIFY_FAILURE, "No artifacts found."
        
        # Check for index.html
        print(f"DEBUG: artifacts type: {type(artifacts)}, first item type: {type(artifacts[0]) if artifacts else 'None'}")
        has_html = any(a['path'] == "index.html" for a in artifacts)
        if not has_html:
            return TaskEvent.VERIFY_FAILURE, "Missing index.html"
        
        # Static analysis of the HTML/JS content
        html_content = ""
        for a in artifacts:
            if a['path'] == "index.html":
                try:
                    phys_path = f"artifact_store/{project_id}/v{plan_version}/{task_id}/index.html"
                    with open(phys_path, 'r', encoding='utf-8') as f:
                        html_content = f.read()
                except Exception as e:
                    return TaskEvent.VERIFY_FAILURE, f"Could not read index.html: {e}"

        # Check for essential game components
        requirements = [
            ("<canvas", "Canvas element missing"),
            ("addEventListener", "Input handling missing"),
            ("requestAnimationFrame", "Game loop missing"),
            ("snake", "Snake logic missing"),
            ("score", "Score tracking missing"),
            ("gameOver", "Game over logic missing")
        ]
        
        for req, err in requirements:
            if req not in html_content.lower():
                return TaskEvent.VERIFY_FAILURE, f"Static analysis failed: {err}"
                
        return TaskEvent.VERIFY_SUCCESS, "All static checks passed."

    # Monkey-patch the execution service instead of verification service
    execution_service.verify = verify_snake_game
    # --------------------------------------------

    # Setup Transport and Scheduler
    transport = InternalTransport()
    scheduler = Scheduler(db_manager, messenger_callback=transport.dispatch)
    
    # Setup Orchestrator
    orchestrator = Orchestrator(
        db_manager=db_manager,
        scheduler=scheduler,
        transport=transport,
        execution_service=execution_service,
        sandbox=sandbox
    )

    # Initialize the run
    project_id, plan_id, task_id = await setup_initial_state(db_manager)

    logger.info("🚀 STARTING RUN 9.1 - BROWSER GAME CHALLENGE")
    logger.info(f"User Prompt: {prompt}")

    # Real LLM Workers
    provider = NvidiaProvider(
        api_key="REDACTED_NVIDIA_KEY",
        model="meta/llama-3.1-70b-instruct"
    )
    planner = PlannerWorker(provider, "meta/llama-3.1-70b-instruct")
    executor = ExecutionWorker(provider, "meta/llama-3.1-70b-instruct")

    async def worker_simulator(project_id, plan_id, task_id):
        logger.info("[SimWorker] Worker simulator started.")
        while orchestrator.running:
            assignment = await transport.poll_dispatch()
            
            if assignment:
                logger.info(f"[SimWorker] RECEIVED ASSIGNMENT: {assignment}")
                t_id = assignment.get("task_id")
                role = assignment.get("role")
                # ...
                
                async with db_manager.session_scope() as session:
                    result = await session.execute(select(Task).filter(Task.id == t_id))
                    task = result.scalars().first()
                    
                    if not task:
                        continue
                    
                    if role == AssignedRole.PLANNER.value:
                        logger.info(f"[SimWorker] Planner processing assignment for task {task.id}")
                        msg = await planner.handle_request(project_id, prompt)
                        event = "PLAN_APPROVED" if msg.header.message_type == MessageType.PLAN_DRAFT_SUBMITTED else "PLAN_REJECTED"
                        payload = {
                            "task_id": task.id,
                            "state_revision": task.state_revision,
                            "event": event,
                            "sender_role": "PLANNER",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            **msg.payload
                        }
                        await transport.publish_response("PLANNER", payload)
                        
                    elif role == AssignedRole.CODER.value:
                        logger.info(f"[SimWorker] Executor processing assignment for task {task.id}")
                        task_def = {"goal": prompt, "acceptance_criteria": ["Valid HTML5/JS", "Snake logic implemented", "UI includes score and restart"]}
                        msg = await executor.handle_assignment(project_id, plan_id, task.id, task_def)
                        payload = {
                            "task_id": task.id,
                            "state_revision": task.state_revision,
                            "event": "CODE_SUBMITTED",
                            "sender_role": "CODER",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            **msg.payload
                        }
                        await transport.publish_response("CODER", payload)
            
            async with db_manager.session_scope() as session:
                result = await session.execute(select(Task).filter(Task.id == task_id))
                task = result.scalars().first()
                if task and task.execution_phase in [ExecutionPhase.COMPLETE, ExecutionPhase.FAILED, ExecutionPhase.FAILED_ITERATION_LIMIT]:
                    logger.info(f"🏁 TASK REACHED TERMINAL STATE: {task.execution_phase}")
                    orchestrator.running = False
                    return

            await asyncio.sleep(0.1)

    orchestrator.running = True
    
    # Start the worker and orchestrator
    print("DEBUG: Starting gather...")
    try:
        await asyncio.gather(
            orchestrator.run_forever(),
            worker_simulator(project_id, plan_id, task_id)
        )
    except asyncio.CancelledError:
        pass
    finally:
        await orchestrator.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
