import asyncio
import logging
import sys
import uuid
import os
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from typing import Tuple

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
from engine.exceptions import WorkerExecutionError, ValidationFailure, EngineConfigurationError
from workers.planner import PlannerWorker
from workers.executor import ExecutionWorker

# Logging setup for forensics
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler("run_corporate_site_forensics.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("RUN_CORPORATE_SITE")

# Global cache for delta-feedback
LAST_VERIFICATION_LOGS = {}

def construct_delta_feedback(logs):
    if not logs:
        return None
    lines = logs.split('\n')
    fails = [line for line in lines if '[FAIL]' in line]
    if not fails:
        return None
    
    report = ["\n--- VALIDATION FAILURE REPORT ---"]
    report.append("Your previous attempt failed the following deterministic criteria:")
    for fail in fails:
        report.append(f"- {fail}")
    
    report.append("\n--- REQUIRED CORRECTIONS ---")
    if "CONTAINS:index.html:<svg" in logs and any("[FAIL]" in l for l in lines if "CONTAINS:index.html:<svg" in l):
        report.append("- The HTML does not contain an inline <svg> element.")
        report.append("- ACTION: Embed the SVG markup directly inside the <body> of index.html.")
        report.append("- WARNING: Do not create a separate logo.svg file.")
    
    if "NOT_EXISTS:logo.svg" in logs and any("[FAIL]" in l for l in lines if "NOT_EXISTS:logo.svg" in l):
        report.append("- A separate logo.svg file was detected.")
        report.append("- ACTION: Delete logo.svg. All assets must be inline.")
    
    report.append("\nCONCLUSION: You are following 'Best Practices' instead of the 'Deterministic Specification'.")
    report.append("You MUST prioritize the Acceptance Criteria over any architectural preference.")
    return "\n".join(report)


class ValidationFailure(Exception):
    """Quality failure: The output does not meet the acceptance criteria."""
    pass

class EngineConfigurationError(Exception):
    """Governance failure: The system is misconfigured (e.g., missing verifier)."""
    pass

async def setup_initial_state(db_manager: DatabaseManager):
    async with db_manager.session_scope() as session:
        project = Project(
            name="Firma Corporate Website",
            created_at=datetime.now(timezone.utc)
        )
        session.add(project)
        await session.flush()

        plan = Plan(
            project_id=project.id,
            version=1,
            name="Corporate Site Plan",
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
            verification_type="structural_web", # EXPLICIT GOVERNANCE
            expected_artifacts=["index.html", "styles.css", "script.js"],
            acceptance_criteria=[
                "EXISTS:index.html",
                "CONTAINS:index.html:<svg",
                "NOT_EXISTS:logo.svg",
                "CONTAINS:index.html:Deterministic Kernel",
                "CONTAINS:index.html:Nervous System",
                "CONTAINS:index.html:Muscles",
                "CONTAINS:index.html:tailwind"
            ],
            updated_at=datetime.now(timezone.utc)
        )
        session.add(task)
        await session.flush()
        
        # --- SURGICAL STATE FORENSICS ---
        res = await session.execute(select(Task.id, Task.state).filter(Task.id == task.id))
        row = res.first()
        logger.info(f"BOOTSTRAP STATE: id={row.id}, state={row.state!r}, type={type(row.state)}")
        # --------------------------------
        
        logger.info(f"Setup complete. Project: {project.id}, Plan: {plan.id}, Task: {task.id}")
        
        # --- BOOTSTRAP INVARIANT CHECK ---
        logger.info("--- BOOTSTRAP INVARIANT SNAPSHOT ---")
        logger.info(f"PROJECT: id={project.id}, active_plan_id={project.active_plan_id}")
        logger.info(f"PLAN:    id={plan.id}, status={plan.status}")
        logger.info(f"TASK:    id={task.id}, plan_id={task.plan_id}, state={task.state}, assigned_worker={task.assigned_worker}")
        logger.info("-----------------------------------")
        
        return project.id, plan.id, task.id

async def verify_deterministic(session, task_id, project_id, plan_version=1, verification_type="csv"):
    logger.info(f"[GovernanceAudit] Verifying task {task_id}")
    # Access db_manager via the session's connection if needed, but here we use the passed session
    result = await session.execute(select(Task).filter(Task.id == task_id))
    task = result.scalars().first()
    if not task:
        raise WorkerExecutionError("Task not found in database")
    
    v_type = getattr(task, "verification_type", None)
    if not v_type:
        logger.error(f"[GovernanceAudit] Task {task_id} has no verification_type defined!")
        raise EngineConfigurationError(f"Task {task_id} is missing required verification_type")
    
    logger.info(f"[GovernanceAudit] Task {task_id} -> Requested Verifier: {v_type}")
    
    try:
        from engine.services.verification_registry import VerificationRegistry
        verifier = VerificationRegistry.get(v_type)
        logger.info(f"[GovernanceAudit] Registry resolved {v_type} to {type(verifier).__name__}")
        
        # Verifier logic: we need a project_id and a workspace.
        # The StructuralWebVerifier handles the workspace creation inside.
        success, logs = await verifier.verify(session, task_id, project_id, plan_version, artifacts=None)
        
        if success:
            logger.info(f"Task {task_id} VERIFIED")
            LAST_VERIFICATION_LOGS[task_id] = None
            return TaskEvent.VERIFY_SUCCESS, logs
        else:
            delta = construct_delta_feedback(logs)
            feedback_logs = delta if delta else logs
            logger.warning(f"Task {task_id} FAILED verification: {feedback_logs}")
            LAST_VERIFICATION_LOGS[task_id] = feedback_logs
            return TaskEvent.VERIFY_FAILURE, feedback_logs
    except ValueError as e:
        logger.error(f"[GovernanceAudit] Registry Error: {str(e)}")
        raise EngineConfigurationError(f"Verifier {v_type} not registered in system")
    except Exception as e:
        logger.exception(f"[GovernanceAudit] Unexpected Error: {str(e)}")
        raise WorkerExecutionError(f"Verification process crashed: {str(e)}")

async def worker_heartbeat(worker_id):
    """Background task to signal the worker loop is still alive."""
    try:
        while True:
            logger.debug(f"[Worker {worker_id}] Heartbeat - Loop is reactive")
            await asyncio.sleep(10)
    except asyncio.CancelledError:
        pass

async def worker_simulator(project_id, plan_id, task_id, orchestrator, transport, db_manager, planner, executor, prompt):
    worker_id = str(uuid.uuid4())[:8]
    logger.info(f"[Worker] Worker loop started (id={worker_id})")
    
    heartbeat_task = asyncio.create_task(worker_heartbeat(worker_id))
    
    try:
        while orchestrator.running:
            try:
                # Industrial Blocking: Wait until an assignment actually arrives
                assignment = await transport.get_dispatch()
                if not assignment:
                    continue
                
                t_id = assignment.get("task_id", "unknown")
                role = assignment.get("role")
                logger.info(f"[Worker {worker_id}] Received assignment for task {t_id} (Role: {role})")
                
                try:
                    async with db_manager.session_scope() as session:
                        logger.info(f"[Worker {worker_id}] DB Session opened for task {t_id}")
                        result = await session.execute(select(Task).filter(Task.id == t_id))
                        task = result.scalars().first()
                        
                        if not task:
                            logger.warning(f"[Worker {worker_id}] Task {t_id} not found in DB. Skipping.")
                            continue
                        
                        if role == AssignedRole.PLANNER.value:
                            logger.info(f"[Worker {worker_id}] Planner processing assignment for task {task.id}")
                            msg = await planner.handle_request(project_id, prompt)
                            event = "PLAN_APPROVED" if msg.header.message_type == MessageType.PLAN_DRAFT_SUBMITTED else "PLAN_REJECTED"
                            payload = {**msg.payload, "logs": "Planning successful"}
                        elif role == AssignedRole.CODER.value:
                            logger.info(f"[Worker {worker_id}] Executor processing assignment for task {task.id}")
                            last_failure = LAST_VERIFICATION_LOGS.get(task.id)
                            task_def = {
                                "goal": prompt, 
                                "acceptance_criteria": task.acceptance_criteria,
                                "previous_failure_feedback": last_failure
                            }
                            msg = await executor.handle_assignment(project_id, plan_id, task.id, task_def)
                            event = "CODE_SUBMITTED"
                            payload = {**msg.payload, "logs": "Implementation submitted"}
                        else:
                            raise ValueError(f"Unsupported role: {role}")

                        response_payload = {
                            "task_id": task.id,
                            "state_revision": task.state_revision,
                            "event": event,
                            "sender_role": role,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            **payload
                        }
                        logger.info(f"[Worker {worker_id}] Execution successful. Publishing {event} for {task.id}")
                        await transport.publish_response(role, response_payload)

                except WorkerExecutionError as wee:
                    event = TaskEvent.WORKER_TIMEOUT.value if wee.error_code == "LLM_TIMEOUT" else TaskEvent.TASK_FAILED.value
                    logger.warning(f"[Worker {worker_id}] Controlled failure: {wee.message}. Publishing {event}")
                    await transport.publish_response(role, {
                        "task_id": t_id,
                        "state_revision": assignment.get("state_revision", 0),
                        "event": event,
                        "sender_role": role,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "logs": wee.message
                    })

                except Exception as e:
                    logger.exception(f"[Worker {worker_id}] Unexpected crash processing task {t_id}: {e}")
                    await transport.publish_response(role, {
                        "task_id": t_id,
                        "state_revision": assignment.get("state_revision", 0),
                        "event": TaskEvent.TASK_FAILED.value,
                        "sender_role": role,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "logs": f"UNHANDLED_EXCEPTION: {str(e)}"
                    })

            except Exception as loop_err:
                logger.exception(f"[Worker {worker_id}] FATAL error in loop body: {loop_err}")
                await asyncio.sleep(1)

    finally:
        heartbeat_task.cancel()

async def main():
    prompt = (
        "Erstelle eine hochprofessionelle Corporate Landing Page für das Projekt 'Firma'.\n\n"
        "Kernvision: 'The Deterministic Kernel for Probabilistic Compute'.\n\n"
        "!!! DETERMINISTIC GOVERNANCE RULES !!!\n"
        "1. Das SVG-Logo MUSS inline im HTML-Body von index.html eingebettet sein.\n"
        "2. Erzeuge UNTER KEINEN UMSTÄNDEN eine separate Datei namens 'logo.svg'.\n"
        "3. Nutze keine <img>-Tags für das Logo; verwende ausschließlich das <svg> Tag direkt im HTML.\n"
        "4. Jede Abweichung von diesen Regeln führt deterministisch zu einem VALIDATION_FAILURE.\n"
        "5. Beste-Praktiken (wie Datei-Auslagerung) sind in diesem Fall UNTERORDNUNG der Spezifikation.\n\n"
        "SELBSTPRÜFUNG VOR AUSGABE:\n"
        "- Enthält index.html ein <svg> Tag?\n"
        "- Wurde KEINE logo.svg Datei erzeugt?\n"
        "- Ist das Logo inline?\n"
        "Wenn nein, korrigiere den Code, bevor du ihn sendest.\n\n"
        "Inhaltliche Anforderungen:\n"
        "1. Branding & Logo: Ein professionelles, minimalistisches SVG-Logo (INLINE!), das die Idee eines 'Kernels' oder einer 'Engine' symbolisiert. Prominent im Header.\n"
        "2. Hero-Sektion: Ein starker, minimalistischer Einstieg mit dem Claim und einer klaren Value Proposition.\n"
        "3. Architektur-Sektion: Erkläre die Analogie des Systems: 'Der Kernel (Das Gehirn)', 'Das Nervensystem (pi-messenger)' und 'Die Muskeln (LLM-Worker)'.\n"
        "4. Governance-Sektion: Hebe die State-Machine, die Plan-Registry und den Artifact Store als Garanten für Determinismus hervor.\n"
        "5. Vision-Sektion: Erkläre den Prozess von der rohen Anfrage über deterministische Validierung zum geprüften Endprodukt.\n"
        "6. Footer: Professioneller Abschluss mit technischen Spezifikationen.\n\n"
        "Technische Anforderungen:\n"
        "- Look & Feel: Modernes Dark-Theme, High-End Enterprise Aesthetic (ähnlich wie Stripe, Vercel oder OpenAI).\n"
        "- Tech-Stack: HTML5, Tailwind CSS (via CDN), Vanilla JavaScript.\n"
        "- Layout: Fully Responsive, saubere Typografie, subtile Animationen via CSS.\n"
        "- Dateien: index.html, styles.css, script.js.\n\n"
        "Liefere den Code in einer strukturierten Form, die direkt in der Sandbox validiert werden kann."
    )
    
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    db_path = f"firma_corporate_site_{run_id}.db"
    logger.info(f"Starting run with isolated database: {db_path}")

    db_manager = DatabaseManager(f"sqlite+aiosqlite:///{db_path}")
    await db_manager.initialize_db()
    from engine.models import Base
    await db_manager.create_tables(Base)

    sandbox = LocalPythonSandbox()
    artifact_store = ArtifactStore()
    verification_service = VerificationService(sandbox)
    execution_service = ExecutionService(sandbox)
    
    from engine.services.verification_registry import VerificationRegistry, BaseVerifier
    class StructuralWebVerifier(BaseVerifier):
        def __init__(self, v_service: VerificationService):
            self.v_service = v_service
        async def verify(self, session, task_id, project_id, plan_version, artifacts) -> Tuple[bool, str]:
            async with db_manager.session_scope() as s:
                res = await s.execute(select(Task).filter(Task.id == task_id))
                task = res.scalars().first()
                if not task: return False, "Task not found"
                workspace = Path(f"artifact_store/{project_id}/v1/{task_id}")
                from engine.services.sandbox import ExecutionResult
                mock_exec_result = ExecutionResult(exit_code=0, stdout="", stderr="", timed_out=False)
                v_result = await self.v_service.verify(task, mock_exec_result, workspace)
                return v_result.passed, "\n".join(v_result.details)

    VerificationRegistry.register("structural_web", lambda: StructuralWebVerifier(verification_service))

    execution_service.verify = verify_deterministic

    transport = InternalTransport()
    scheduler = Scheduler(db_manager, messenger_callback=transport.dispatch)
    await scheduler.recover_stale_claims()
    
    orchestrator = Orchestrator(
        db_manager=db_manager,
        scheduler=scheduler,
        transport=transport,
        execution_service=execution_service,
        sandbox=sandbox
    )

    project_id, plan_id, task_id = await setup_initial_state(db_manager)
    logger.info("STARTING RUN - CORPORATE WEBSITE CHALLENGE")

    provider = NvidiaProvider(
        api_key="REDACTED_NVIDIA_KEY",
        model="meta/llama-3.1-70b-instruct"
    )
    planner = PlannerWorker(provider, "meta/llama-3.1-70b-instruct", dummy_mode=False)
    executor = ExecutionWorker(provider, "meta/llama-3.1-70b-instruct", dummy_mode=True)

    orchestrator.running = True
    
    orchestrator_task = asyncio.create_task(orchestrator.run_forever())
    worker_task = asyncio.create_task(worker_simulator(project_id, plan_id, task_id, orchestrator, transport, db_manager, planner, executor, prompt))
    
    try:
        await asyncio.gather(orchestrator_task, worker_task)
    except Exception as e:
        logger.exception(f"Unexpected System Crash: {e}")
    finally:
        await orchestrator.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
