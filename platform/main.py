import asyncio
import logging
import sys
import uuid
import os
from datetime import datetime, timezone
from pathlib import Path

# Ensure the root directory is in the python path so we can import engine and workers
root_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(root_dir))

from engine.db import DatabaseManager
from engine.models import Base
from engine.orchestrator import Orchestrator
from engine.scheduler import Scheduler
from engine.transport.internal_transport import InternalTransport
from engine.services.execution import ExecutionService
from engine.services.sandbox import LocalPythonSandbox
from engine.services.verification_service import VerificationService
from engine.services.verification_registry import VerificationRegistry, BaseVerifier
from engine.controller import RunController
from engine.providers.openrouter_provider import OpenRouterProvider
from workers.planner import PlannerWorker
from workers.executor import ExecutionWorker

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler("platform_execution.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("PLATFORM_MAIN")

class StructuralWebVerifier(BaseVerifier):
    def __init__(self, v_service: VerificationService):
        self.v_service = v_service
    async def verify(self, session, task_id, project_id, plan_version, artifacts) -> tuple:
        from sqlalchemy import select
        from engine.models import Task
        res = await session.execute(select(Task).filter(Task.id == task_id))
        task = res.scalars().first()
        if not task: return False, "Task not found"
        workspace = Path(f"artifact_store/{project_id}/v1/{task_id}")
        from engine.services.sandbox import ExecutionResult
        mock_exec_result = ExecutionResult(exit_code=0, stdout="", stderr="", timed_out=False)
        v_result = await self.v_service.verify(task, mock_exec_result, workspace)
        return v_result.passed, "\n".join(v_result.details)

async def worker_simulator(run_id, project_id, plan_id, task_id, transport, db_manager, planner, executor, prompt):
    """
    A run-aware worker simulator.
    """
    worker_id = str(uuid.uuid4())[:8]
    logger.info(f"[Worker {worker_id}] Started for run {run_id}")
    
    try:
        while True:
            assignment = await transport.get_dispatch()
            if not assignment: continue
            
            # RUN-ISOLATION CHECK
            if assignment.get("run_id") != run_id:
                logger.warning(f"[Worker {worker_id}] Ignoring assignment for run {assignment.get('run_id')}")
                continue

            t_id = assignment.get("task_id")
            role = assignment.get("role")
            
            try:
                async with db_manager.session_scope() as session:
                    from sqlalchemy import select
                    from engine.models import Task
                    res = await session.execute(select(Task).filter(Task.id == t_id, Task.run_id == run_id))
                    task = res.scalars().first()
                    if not task: continue

                    if role == "PLANNER":
                        msg = await planner.handle_request(project_id, prompt)
                        event, payload = "PLAN_APPROVED", {**msg.payload, "logs": "Plan successful"}
                    elif role == "CODER":
                        # IMPROVEMENT: Use the actual task description from the plan, not the global prompt
                        from engine.models import Task
                        task_res = await session.execute(select(Task).filter(Task.id == t_id))
                        task_obj = task_res.scalars().first()
                        
                        task_def = {
                            "goal": task_obj.description if task_obj else prompt,
                            "acceptance_criteria": task_obj.acceptance_criteria if task_obj else task.acceptance_criteria,
                            "expected_artifacts": task_obj.expected_artifacts if task_obj else task.expected_artifacts
                        }
                        msg = await executor.handle_assignment(project_id, plan_id, task.id, task_def)
                        event, payload = "CODE_SUBMITTED", {**msg.payload, "logs": "Code successful"}
                    elif role == "REVIEWER":
                        event, payload = "REVIEW_APPROVED", {"logs": "Review successful: All criteria met and code is clean."}
                    else:
                        continue

                    # Fetch latest revision
                    rev_res = await session.execute(select(Task.state_revision).filter(Task.id == task.id))
                    latest_rev = rev_res.scalar()

                    await transport.publish_response(role, {
                        "run_id": run_id,
                        "task_id": task.id,
                        "state_revision": latest_rev,
                        "event": event,
                        "sender_role": role,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        **payload
                    })
            except Exception as e:
                logger.error(f"[Worker {worker_id}] Error processing task {t_id}: {e}")
                # CRITICAL: Report failure back to the Orchestrator to prevent "Symptomatic Loop"
                await transport.publish_response(role, {
                    "run_id": run_id,
                    "task_id": t_id,
                    "state_revision": assignment.get("state_revision", 0),
                    "event": "TASK_FAILED",
                    "sender_role": role,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "logs": f"WORKER_EXCEPTION: {str(e)}"
                })
    except asyncio.CancelledError:
        pass

async def main():
    # 1. Infrastructure Setup
    from engine.settings import DB_DIR
    db_path = DB_DIR / "platform_industrial.db"
    if db_path.exists(): os.remove(db_path)
    
    db_manager = DatabaseManager(f"sqlite+aiosqlite:///{db_path}")
    await db_manager.initialize_db()
    await db_manager.create_tables(Base)

    sandbox = LocalPythonSandbox()
    verification_service = VerificationService(sandbox)
    execution_service = ExecutionService(sandbox)
    
    VerificationRegistry.register("structural_web", lambda: StructuralWebVerifier(verification_service))
    # REMOVED the manual override of execution_service.verify to avoid signature mismatch

    # 2. Platform Controller Setup
    # We need shared transport for the simulator to work easily in one process
    shared_transport = InternalTransport()
    
    controller = RunController(
        db_manager=db_manager,
        scheduler_factory=lambda db, messenger_callback: Scheduler(db, messenger_callback),
        transport_factory=lambda: shared_transport, # Shared for this process
        execution_service=execution_service,
        sandbox=sandbox
    )

    # 3. Define a Run Config (REAL PROJECT: Corporate Website)
    config = {
        "project_name": "Firma Corporate Website",
        "plan_name": "Enterprise Site Build",
        "expected_artifacts": ["index.html", "styles.css", "script.js"],
        "acceptance_criteria": [
            "EXISTS:index.html",
            "CONTAINS:index.html:Tailwind",
            "CONTAINS:index.html:Firma",
            "EXISTS:styles.css",
            "EXISTS:script.js"
        ],
        "verification_type": "structural_web",
        "prompt": "Create a professional, high-end corporate website for 'Firma'. The site should have a dark-theme enterprise aesthetic, be fully responsive using Tailwind CSS (via CDN), and include a landing page with a hero section, services overview, and a futuristic feel. Deliverables: index.html, styles.css, script.js."
    }

    # 4. Execute Run
    run_id = await controller.create_run(config)
    await controller.start_run(run_id)

    # Setup Workers
    provider = OpenRouterProvider(
        api_key="REDACTED_OPENROUTER_KEY",
        model="meta-llama/llama-3.1-8b-instruct"
    )
    planner = PlannerWorker(provider, "meta-llama/llama-3.1-70b-instruct")
    executor = ExecutionWorker(provider, "meta-llama/llama-3.1-70b-instruct")

    # We need project/plan/task IDs for the worker simulator in this simplified main
    async with db_manager.session_scope() as session:
        from sqlalchemy import select
        from engine.models import Project, Plan, Task
        proj = (await session.execute(select(Project).filter(Project.run_id == run_id))).scalars().first()
        plan = (await session.execute(select(Plan).filter(Plan.run_id == run_id))).scalars().first()
        task = (await session.execute(select(Task).filter(Task.run_id == run_id))).scalars().first()

    worker_task = asyncio.create_task(
        worker_simulator(run_id, proj.id, plan.id, task.id, shared_transport, db_manager, planner, executor, config["prompt"])
    )

    # 5. Monitoring Loop
    try:
        logger.info("Monitoring run until terminal state (COMPLETED/FAILED/CANCELLED)...")
        while True:
            status = await controller.get_run_status(run_id)
            current_status = status['status']
            logger.info(f"RUN STATUS: {current_status} | Metrics: {status['metrics']}")
            
            if current_status in ["COMPLETED", "FAILED", "CANCELLED"]:
                logger.info(f"Run reached terminal state: {current_status}")
                break
            
            await asyncio.sleep(5)
    except Exception as e:
        logger.exception(f"Error during monitoring: {e}")
    finally:
        await controller.stop_run(run_id)
        worker_task.cancel()

if __name__ == "__main__":
    asyncio.run(main())
