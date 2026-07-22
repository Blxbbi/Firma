import asyncio
import logging
import sys
import uuid
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
        logging.FileHandler("run_8_1_forensics.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("RUN_8_1")

async def setup_initial_state(db_manager: DatabaseManager):
    async with db_manager.session_scope() as session:
        project = Project(
            name="Run 8.1 - CSV Aggregator",
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

        # ACTIVATE PLAN: The scheduler only assigns tasks from the active plan.
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
        "Schreibe ein Python CLI-Tool `main.py`, das eine CSV-Datei mit zwei Spalten `name,value` einliest und für jeden Namen die Summe der Werte ausgibt. "
        "Das Tool soll robust gegen leere Zeilen, ungültige Zahlen und fehlende Spalten sein. "
        "\n\nBUG REPORT: The previous version crashed with 'TypeError: float() argument must be a string or a real number, not NoneType' "
        "when a row had a name but the value column was empty. Ensure that you check if the value is not None before converting to float."
    )
    
    # Setup Database
    db_manager = DatabaseManager("sqlite+aiosqlite:///firma_run_8_1_clean.db")
    await db_manager.initialize_db()
    from engine.models import Base
    await db_manager.create_tables(Base)

    # Setup Services
    sandbox = LocalPythonSandbox()
    artifact_store = ArtifactStore()
    verification_service = VerificationService(sandbox)
    execution_service = ExecutionService(sandbox)
    
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

    logger.info("🚀 STARTING RUN 8.1 - BOUNDED FREE AUTONOMOUS LOOP")
    logger.info(f"User Prompt: {prompt}")

    # Real LLM Workers
    provider = NvidiaProvider(
        api_key="REDACTED_NVIDIA_KEY",
        model="meta/llama-3.1-70b-instruct"
    )
    planner = PlannerWorker(provider, "meta/llama-3.1-70b-instruct")
    executor = ExecutionWorker(provider, "meta/llama-3.1-70b-instruct")

    async def worker_simulator(project_id, plan_id, task_id):
        while orchestrator.running:
            # 1. Check for assignments from the transport
            assignment = await transport.poll_dispatch()
            
            if assignment:
                t_id = assignment.get("task_id")
                role = assignment.get("role")
                
                async with db_manager.session_scope() as session:
                    result = await session.execute(select(Task).filter(Task.id == t_id))
                    task = result.scalars().first()
                    
                    if not task:
                        continue
                    
                    # Process based on role
                    if role == AssignedRole.PLANNER.value:
                        logger.info(f"[SimWorker] Planner processing assignment for task {task.id}")
                        msg = await planner.handle_request(project_id, prompt)
                        
                        # Map MessageType to TaskEvent
                        event = "PLAN_APPROVED" if msg.header.message_type == MessageType.PLAN_DRAFT_SUBMITTED else "PLAN_REJECTED"
                        
                        # Construct a flat WorkerResponse-compatible payload
                        # Remove the nested 'payload' key because transport.publish_response already wraps it
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
                        task_def = {"goal": prompt, "acceptance_criteria": ["Valid CSV output", "Handle empty lines", "Handle invalid numbers"]}
                        msg = await executor.handle_assignment(project_id, plan_id, task.id, task_def)
                        
                        # Construct a flat WorkerResponse-compatible payload
                        # Remove the nested 'payload' key because transport.publish_response already wraps it
                        payload = {
                            "task_id": task.id,
                            "state_revision": task.state_revision,
                            "event": "CODE_SUBMITTED",
                            "sender_role": "CODER",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            **msg.payload
                        }
                        await transport.publish_response("CODER", payload)
            
            # 2. Termination check (check if the primary task is done)
            async with db_manager.session_scope() as session:
                result = await session.execute(select(Task).filter(Task.id == task_id))
                task = result.scalars().first()
                if task and task.execution_phase in [ExecutionPhase.COMPLETE, ExecutionPhase.FAILED, ExecutionPhase.FAILED_ITERATION_LIMIT]:
                    logger.info(f"🏁 TASK REACHED TERMINAL STATE: {task.execution_phase}")
                    orchestrator.running = False
                    return

            await asyncio.sleep(0.1)

    # Run the orchestrator and simulator concurrently
    orchestrator.running = True
    
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
