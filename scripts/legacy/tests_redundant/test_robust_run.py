import os
import asyncio
import logging
import uuid
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from engine.db import DatabaseManager
from engine.models import Base, Plan, Task, Message, MessageHeader, MessageType
from engine.repository import MessageRepository
from engine.workflow import process_task_message
from engine.services.sandbox import LocalPythonSandbox
from engine.services.execution import ExecutionService
from engine.orchestrator import Orchestrator
from sqlalchemy import select

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("firma-robust-test")

async def setup_robust_scenario(session, prompt: str):
    """
    Sets up a scenario with MULTIPLE criteria to test the Robust Path.
    """
    logger.info(f"Setting up robust scenario for: {prompt}")
    
    project_id = "P-ROBUST"
    from engine.models import Project
    project = Project(id=project_id, name="Robust Integration Test Project")
    session.add(project)
    
    plan_id = f"plan-{uuid.uuid4().hex[:8]}"
    plan = Plan(id=plan_id, project_id=project_id, version=1, name=prompt[:30], status="IN_PROGRESS")
    session.add(plan)
    project.active_plan_id = plan_id
    
    task_id = "T1"
    # MULTI-CRITERIA: 3 tests to ensure correctness across ranges
    criteria = [
        "CMD:python main.py 2 3:6.0",
        "CMD:python main.py -2 3:-6.0",
        "CMD:python main.py 0 5:0.0"
    ]
    task = Task(
        id=task_id, 
        plan_id=plan_id, 
        state="READY", 
        execution_phase="CODING", 
        assigned_role="CODER",
        expected_artifacts=["main.py"],
        acceptance_criteria=criteria
    )
    session.add(task)
    await session.commit()
    
    return project_id, plan_id, task_id

async def main():
    db_file = "firma_robust_run.db"
    if os.path.exists(db_file): 
        try:
            os.remove(db_file)
        except OSError:
            pass
            
    db_url = f"sqlite+aiosqlite:///{db_file}"
    db_manager = DatabaseManager(db_url)
    await db_manager.initialize_db()
    await db_manager.create_tables(Base)
    
    artifact_dir = tempfile.TemporaryDirectory()
    os.environ["FIRMA_ARTIFACT_STORE_DIR"] = artifact_dir.name
    
    sandbox = LocalPythonSandbox()
    exec_service = ExecutionService(sandbox)
    
    class SimpleScheduler:
        def assign_unassigned_ready_tasks(self):
            pass 
    scheduler = SimpleScheduler()
    
    class MockTransport:
        async def poll(self): return []
        async def connect(self): pass
        async def disconnect(self): pass

    transport = MockTransport()
    
    orchestrator = Orchestrator(db_manager, scheduler, transport, exec_service, sandbox)
    orch_task = asyncio.create_task(orchestrator.run_forever())
    
    try:
        # Using the same validated multiplication code
        real_code = "import sys\n\ndef main():\n    if len(sys.argv) != 3:\n        sys.exit(1)\n    try:\n        num1 = float(sys.argv[1])\n        num2 = float(sys.argv[2])\n        print(num1 * num2)\n    except ValueError:\n        sys.exit(1)\n\nif __name__ == '__main__':\n    main()"
            
        prompt = "Write a Python CLI script that multiplies two numbers passed as arguments."
        
        async with db_manager.session_scope() as session:
            project_id, plan_id, task_id = await setup_robust_scenario(session, prompt)
        
        worker_payload = {
            "message_id": str(uuid.uuid4()),
            "task_id": task_id,
            "state_revision": 0,
            "sender_role": "CODER",
            "event": "CODE_SUBMITTED",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "artifacts": {
                "files": [
                    {"path": "main.py", "action": "CREATE", "content": real_code}
                ]
            }
        }
        
        msg = Message(
            header=MessageHeader(
                message_id=worker_payload["message_id"],
                sender="llm-worker",
                recipient="engine",
                message_type=MessageType.TASK_RESULT,
                plan_id=plan_id
            ),
            payload=worker_payload
        )
        
        async with db_manager.session_scope() as session:
            success = await process_task_message(session, msg, task_id, MessageType.TASK_RESULT, project_id)
            if not success:
                logger.error("Pipeline failed to process TASK_RESULT!")
                return

        logger.info("TASK_RESULT processed. Waiting for multi-criteria verification...")
        
        while True:
            async with db_manager.session_scope() as session:
                result = await session.execute(select(Task).filter(Task.id == task_id))
                task = result.scalars().first()
                
                if task and task.state == "VERIFIED":
                    logger.info(f"🚀 Robust Path Verified: Task {task_id} passed all criteria!")
                    break
                elif task and task.state == "READY" and task.execution_phase != "CODING":
                    logger.error(f"❌ Robust Path failed: Task {task_id} reset to READY.")
                    break
            await asyncio.sleep(0.5)
            
    finally:
        await orchestrator.stop()
        orch_task.cancel()
        artifact_dir.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
