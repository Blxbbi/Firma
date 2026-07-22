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

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler("run_super_final.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("SUPER_FINAL")

async def setup_initial_state(db_manager: DatabaseManager):
    async with db_manager.session_scope() as session:
        project = Project(name="Super Final Test", created_at=datetime.now(timezone.utc))
        session.add(project)
        await session.flush()

        plan = Plan(project_id=project.id, version=1, name="Mock Plan", status="IN_PROGRESS", created_at=datetime.now(timezone.utc))
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
        
        # CRITICAL: Verify consistency before committing
        assert task.plan_id == project.active_plan_id, f"Plan ID mismatch: {task.plan_id} != {project.active_plan_id}"
        
        await session.commit()
        return project.id, plan.id, task.id

async def main():
    db_path = f"firma_test_{int(datetime.now().timestamp())}.db"
    # os.remove(db_path) # Disabled to avoid WinError 32 lock issues
        
    db_manager = DatabaseManager(f"sqlite+aiosqlite:///{db_path}")
    await db_manager.initialize_db()
    from engine.models import Base
    await db_manager.create_tables(Base)

    sandbox = LocalPythonSandbox()
    artifact_store = ArtifactStore()
    execution_service = ExecutionService(sandbox)
    
    # ALWAYS SUCCESS VERIFIER
    async def verify_always_success(session, task_id, project_id, plan_version, **kwargs):
        logger.info(f"✅ MOCK VERIFIER: Task {task_id} is SUCCESSFUL")
        return TaskEvent.VERIFY_SUCCESS, "Mock Success"

    execution_service.verify = verify_always_success

    transport = InternalTransport()
    scheduler = Scheduler(db_manager, messenger_callback=transport.dispatch)
    orchestrator = Orchestrator(db_manager, scheduler, transport, execution_service, sandbox)

    project_id, plan_id, task_id = await setup_initial_state(db_manager)

    async def worker_simulator():
        logger.info("[MockWorker] Simulator started.")
        while orchestrator.running:
            assignment = await transport.poll_dispatch()
            if assignment:
                t_id = assignment.get("task_id")
                role = assignment.get("role")
                
                async with db_manager.session_scope() as session:
                    result = await session.execute(select(Task).filter(Task.id == t_id))
                    task = result.scalars().first()
                    if not task: continue
                    
                    if role == AssignedRole.PLANNER.value:
                        logger.info(f"Mocking PLANNER for {t_id}")
                        payload = {
                            "task_id": task.id,
                            "state_revision": task.state_revision,
                            "event": "PLAN_APPROVED",
                            "sender_role": "PLANNER",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "plan": {"steps": []}
                        }
                        await transport.publish_response("PLANNER", payload)
                        
                    elif role == AssignedRole.CODER.value:
                        logger.info(f"Mocking CODER for {t_id}")
                        # We MUST create a fake artifact to satisfy the Guardian
                        await artifact_store.persist_artifacts(
                            session, project_id, 1, task.id, 
                            [{"path": "index.html", "action": "CREATE", "content": "<html>Mock</html>"}]
                        )
                        payload = {
                            "task_id": task.id,
                            "state_revision": task.state_revision,
                            "event": "CODE_SUBMITTED",
                            "sender_role": "CODER",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "artifacts": [
                                {"path": "index.html", "action": "CREATE", "content": "<html>Mock</html>"}
                            ]
                        }
                        await transport.publish_response("CODER", payload)

                    elif role == AssignedRole.REVIEWER.value:
                        logger.info(f"Mocking REVIEWER for {t_id}")
                        payload = {
                            "task_id": task.id,
                            "state_revision": task.state_revision,
                            "event": "REVIEW_APPROVED",
                            "sender_role": "REVIEWER",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "artifacts": []
                        }
                        await transport.publish_response("REVIEWER", payload)
            
            async with db_manager.session_scope() as session:
                result = await session.execute(select(Task).filter(Task.id == task_id))
                task = result.scalars().first()
                if task and task.execution_phase in [ExecutionPhase.COMPLETE, ExecutionPhase.FAILED]:
                    logger.info(f"🏁 TERMINAL STATE REACHED: {task.execution_phase}")
                    orchestrator.running = False
                    return
            await asyncio.sleep(0.1)

    orchestrator.running = True
    worker_task = asyncio.create_task(worker_simulator())
    try:
        await orchestrator.run_forever()
    except asyncio.CancelledError:
        pass
    finally:
        worker_task.cancel()
        await orchestrator.stop()

if __name__ == "__main__":
    asyncio.run(main())
