import asyncio
import logging
import os
import shutil
import sys
from engine.db import init_db, Session
from engine.models import Plan, Task, MessageType, Message, MessageHeader
from engine.repository import MessageRepository
from engine.services.execution import ExecutionService
from engine.services.sandbox import LocalSandbox

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

async def test_sandbox_execution_flow():
    # Cleanup
    if os.path.exists("engine.db"):
        os.remove("engine.db")
    if os.path.exists("sandbox_workspace"):
        shutil.rmtree("sandbox_workspace")

    init_db()

    with Session() as session:
        repo = MessageRepository(session)

        # 1. Setup a plan and a task in SUBMITTED state
        p = Plan(name="Sandbox Test Plan", status="IN_PROGRESS")
        session.add(p)
        session.commit()

        task_id = "T1"
        t = Task(
            id=task_id, 
            plan_id=p.id, 
            state="SUBMITTED", 
            expected_artifacts=["result.txt"], 
            acceptance_criteria=["exists"]
        )
        session.add(t)
        session.commit()

        # 2. Initialize ExecutionService with LocalSandbox
        sandbox = LocalSandbox()
        execution_service = ExecutionService(session, sandbox)

        # 3. Run execution service
        print("\n--- Running Execution Service ---")
        await execution_service.process_submitted_tasks()

        # 4. Verify results
        session.expire_all()
        task_after = repo.get_task(task_id)
        print(f"Task {task_id} state after execution: {task_after.state}")

        if task_after.state == "VERIFIED":
            print("SUCCESS: Task transitioned to VERIFIED")
        else:
            print(f"FAILURE: Task state is {task_after.state}")

async def test_sandbox_failure_flow():
    # Cleanup
    if os.path.exists("engine.db"):
        os.remove("engine.db")
    if os.path.exists("sandbox_workspace"):
        shutil.rmtree("sandbox_workspace")

    init_db()

    with Session() as session:
        repo = MessageRepository(session)

        # 1. Setup a plan and a task in SUBMITTED state
        p = Plan(name="Sandbox Failure Plan", status="IN_PROGRESS")
        session.add(p)
        session.commit()

        task_id = "T_FAIL"
        t = Task(
            id=task_id, 
            plan_id=p.id, 
            state="SUBMITTED", 
            expected_artifacts=[], 
            acceptance_criteria=[]
        )
        session.add(t)
        session.commit()

        # 2. Initialize ExecutionService with LocalSandbox
        sandbox = LocalSandbox()
        execution_service = ExecutionService(session, sandbox)

        # 3. Run execution service
        # We'll mock the code to be invalid to force a failure
        # But ExecutionService is hardcoded to use main.py. 
        # I'll modify ExecutionService to take the code as an argument if I want to test failures properly,
        # or I can just create a task that will fail.
        
        # For now, let's just test the happy path first.
        print("\n--- Testing Failure Flow (expecting failure because no code is provided by default) ---")
        await execution_service.process_submitted_tasks()

        # 4. Verify results
        session.expire_all()
        task_after = repo.get_task(task_id)
        print(f"Task {task_id} state after execution: {task_after.state}")

        if task_after.state == "FAILED":
            print("✅ Success: Task transitioned to FAILED")
        else:
            print(f"❌ Failure: Task state is {task_after.state}")

if __name__ == "__main__":
    asyncio.run(test_sandbox_execution_flow())
    asyncio.run(test_sandbox_failure_flow())
