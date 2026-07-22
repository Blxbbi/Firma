import asyncio
import logging
import os
import shutil
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from engine.db import init_db, Session as EngineSession
from engine.models import Plan, Task, Message, MessageType, MessageHeader, Base
from engine.repository import MessageRepository
from engine.schemas.llm import LLMResponse
from engine.providers.mock import MockLLMProvider, MockMode
from workers.llm_worker import LLMWorker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TEST_DB_URL = "sqlite:///test_engine.db"

async def run_test_case(mode, expected_final_state, description):
    print(f"\n--- Testing Case: {description} (Mode: {mode}) ---")
    
    # 1. Setup isolated DB for this test case
    if os.path.exists("test_engine.db"):
        try:
            os.remove("test_engine.db")
        except PermissionError:
            pass
    if os.path.exists("sandbox_workspace"):
        try:
            shutil.rmtree("sandbox_workspace")
        except PermissionError:
            pass

    # Create a fresh engine and session factory for the test
    engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as setup_session:
        repo = MessageRepository(setup_session)

        # 2. Setup Plan and Task
        p = Plan(name="LLM Test Plan", status="IN_PROGRESS")
        setup_session.add(p)
        setup_session.commit()

        task_id = "T_LLM"
        t = Task(
            id=task_id, 
            plan_id=p.id, 
            state="READY", 
            expected_artifacts=["main.py"], 
            acceptance_criteria=["exists"]
        )
        setup_session.add(t)
        setup_session.commit()

        # Manual transition to ASSIGNED
        from datetime import datetime, timedelta
        t.state = "ASSIGNED"
        t.assignment_timeout = datetime.utcnow() + timedelta(seconds=30)
        setup_session.commit()

        # 3. Setup Worker with Mock Messenger
        def mock_messenger(msg):
            from engine.workflow import process_message_workflow
            process_message_workflow(setup_session, msg, 
                                    task_id=msg.payload.get("task_id") if msg.payload else None,
                                    event=msg.header.message_type if msg.header.message_type in [MessageType.TASK_ACK, MessageType.TASK_RESULT, MessageType.STATUS_UPDATE, MessageType.ERROR_REPORT] else None)

        provider = MockLLMProvider(mode)
        worker = LLMWorker(mock_messenger, provider)

        # 4. Trigger Assignment
        assignment_msg = Message(
            header=MessageHeader(
                sender="Engine",
                recipient="LLMWorker",
                message_type=MessageType.TASK_ASSIGNMENT,
                plan_id=p.id
            ),
            payload={"task_id": task_id}
        )
        worker.handle_message(assignment_msg)

        # 5. If it was a successful TASK_RESULT, we need to run the ExecutionService
        if mode == MockMode.HAPPY:
            from engine.services.execution import ExecutionService
            from engine.services.sandbox import Sandbox, SandboxResult
            class DummySandbox(Sandbox):
                def run(self, task_id, code_or_files):
                    return SandboxResult(True, 0, "ok", "", [], "cmd", "cwd")
            
            exec_service = ExecutionService(setup_session, DummySandbox())
            await exec_service.process_submitted_tasks()

        # 6. VERIFICATION: Use a FRESH session to avoid Identity Map issues
        # We MUST create a new session to see the changes committed by the worker/workflow
        with SessionLocal() as verification_session:
            final_task = verification_session.query(Task).get(task_id)
            print(f"Final Task State (Fresh Session): {final_task.state}")

            if final_task.state == expected_final_state:
                print(f"SUCCESS: {description}")
            else:
                print(f"FAILURE: {description} (Expected {expected_final_state}, got {final_task.state})")

async def main():
    await run_test_case(MockMode.HAPPY, "VERIFIED", "Happy Path")
    await run_test_case(MockMode.INVALID_JSON, "FAILED", "Invalid JSON")
    await run_test_case(MockMode.INVALID_SCHEMA, "FAILED", "Invalid Schema (Path Traversal)")

    print("\n--- Testing Case 4: Valid JSON but Sandbox Failure ---")
    # Reset for Case 4
    if os.path.exists("test_engine.db"):
        try:
            os.remove("test_engine.db")
        except PermissionError:
            pass
    if os.path.exists("sandbox_workspace"):
        try:
            shutil.rmtree("sandbox_workspace")
        except PermissionError:
            pass
    
    engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as setup_session:
        repo = MessageRepository(setup_session)
        provider = MockLLMProvider(MockMode.HAPPY)
        
        def mock_messenger(msg):
            from engine.workflow import process_message_workflow
            process_message_workflow(setup_session, msg, 
                                    task_id=msg.payload.get("task_id") if msg.payload else None,
                                    event=msg.header.message_type if msg.header.message_type in [MessageType.TASK_ACK, MessageType.TASK_RESULT, MessageType.STATUS_UPDATE, MessageType.ERROR_REPORT] else None)

        worker = LLMWorker(mock_messenger, provider)

        p = Plan(name="Sandbox Fail Plan", status="IN_PROGRESS")
        setup_session.add(p)
        setup_session.commit()
        task_id = "T_SANDBOX_FAIL"
        t = Task(id=task_id, plan_id=p.id, state="ASSIGNED", expected_artifacts=[], acceptance_criteria=[])
        setup_session.add(t)
        setup_session.commit()

        assignment_msg = Message(
            header=MessageHeader(sender="Engine", recipient="LLMWorker", message_type=MessageType.TASK_ASSIGNMENT, plan_id=p.id),
            payload={"task_id": task_id}
        )
        worker.handle_message(assignment_msg)

        from engine.services.execution import ExecutionService
        from engine.services.sandbox import Sandbox, SandboxResult
        class AlwaysFailSandbox(Sandbox):
            def run(self, task_id, code_or_files):
                return SandboxResult(False, 1, "", "Error", [], "cmd", "cwd")
        
        exec_service = ExecutionService(setup_session, AlwaysFailSandbox())
        await exec_service.process_submitted_tasks()

        with SessionLocal() as verification_session:
            final_task = verification_session.query(Task).get(task_id)
            print(f"Final Task State (Fresh Session): {final_task.state}")
            if final_task.state == "FAILED":
                print("SUCCESS: Case 4")
            else:
                print(f"FAILURE: Case 4 (Expected FAILED, got {final_task.state})")

if __name__ == "__main__":
    asyncio.run(main())
