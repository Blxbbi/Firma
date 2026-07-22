import asyncio
import os
import shutil
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from engine.db import Base
from engine.models import (
    Plan, Task, Message, MessageHeader, MessageType, 
    PlanDraftSchema, PlannerOutput, PlannedArtifact
)
from engine.repository import MessageRepository
from engine.providers.mock import MockLLMProvider, MockMode
from engine.services.plan_instantiator import PlanInstantiationService
from engine.workflow import process_message_workflow
from workers.planner_worker import PlannerWorker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TEST_DB_URL = "sqlite:///test_planner_integration.db"

def setup_test_db():
    if os.path.exists("test_planner_integration.db"):
        try:
            os.remove("test_planner_integration.db")
        except PermissionError:
            pass
    if os.path.exists("sandbox_workspace"):
        try:
            shutil.rmtree("sandbox_workspace")
        except PermissionError:
            pass
    
    engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)

async def run_integration_test():
    print("\n--- Starting Planner Integration Test ---")
    
    # Case 1: Happy Path
    print("\n--- Case 1: Happy Path (Successful Plan Generation) ---")
    engine, SessionLocal = setup_test_db()
    
    with SessionLocal() as setup_session:
        # 1. Setup Messenger that routes messages to the workflow
        def mock_messenger(msg):
            process_message_workflow(setup_session, msg)

        provider = MockLLMProvider(MockMode.HAPPY)
        planner = PlannerWorker(mock_messenger, provider)

        # 2. Send PLAN_REQUEST
        plan_request_msg = Message(
            header=MessageHeader(
                sender="User",
                recipient="PlannerWorker",
                message_type=MessageType.PLAN_REQUEST,
                plan_id="P_INTEGRATION_1"
            ),
            payload={"goal": "Create a python script that prints hello world"}
        )
        
        planner.handle_message(plan_request_msg)
        setup_session.commit()

        # 3. Verify Plan and Tasks in DB
        with SessionLocal() as verification_session:
            plan = verification_session.query(Plan).filter_by(id="P_INTEGRATION_1").first()
            assert plan is not None, "Plan should have been created"
            print(f"Plan found: {plan.name} (Status: {plan.status})")
            
            tasks = verification_session.query(Task).filter_by(plan_id=plan.id).all()
            assert len(tasks) > 0, "Plan should have tasks"
            print(f"Found {len(tasks)} tasks.")
            for t in tasks:
                print(f" - Task {t.id}: {t.description} (State: {t.state})")
                assert t.state == "READY" or t.state == "BLOCKED"

            print("SUCCESS: Happy Path Integration")

    # Case 2: Refusal Path (Empty JSON)
    print("\n--- Case 2: Refusal Path (LLM returns {}) ---")
    engine, SessionLocal = setup_test_db()
    
    with SessionLocal() as setup_session:
        def mock_messenger(msg):
            process_message_workflow(setup_session, msg)

        provider = MockLLMProvider(MockMode.INVALID_JSON) # Using INVALID_JSON to trigger refusal/error in mock
        planner = PlannerWorker(mock_messenger, provider)

        plan_request_msg = Message(
            header=MessageHeader(
                sender="User",
                recipient="PlannerWorker",
                message_type=MessageType.PLAN_REQUEST,
                plan_id="P_INTEGRATION_2"
            ),
            payload={"goal": "Impossible goal"}
        )
        
        planner.handle_message(plan_request_msg)
        setup_session.commit()

        # Verify no plan was created
        with SessionLocal() as verification_session:
            plan = verification_session.query(Plan).filter_by(id="P_INTEGRATION_2").first()
            assert plan is None, "No plan should have been created for a refusal"
            print("SUCCESS: Refusal Path (No plan created)")

    # Case 3: Schema Violation
    print("\n--- Case 3: Schema Violation (Bad JSON Structure) ---")
    engine, SessionLocal = setup_test_db()
    
    with SessionLocal() as setup_session:
        def mock_messenger(msg):
            process_message_workflow(setup_session, msg)

        provider = MockLLMProvider(MockMode.INVALID_SCHEMA) # Triggers schema error in mock
        planner = PlannerWorker(mock_messenger, provider)

        plan_request_msg = Message(
            header=MessageHeader(
                sender="User",
                recipient="PlannerWorker",
                message_type=MessageType.PLAN_REQUEST,
                plan_id="P_INTEGRATION_3"
            ),
            payload={"goal": "Schema violation goal"}
        )
        
        planner.handle_message(plan_request_msg)
        setup_session.commit()

        # Verify no plan was created
        with SessionLocal() as verification_session:
            plan = verification_session.query(Plan).filter_by(id="P_INTEGRATION_3").first()
            assert plan is None, "No plan should have been created for a schema violation"
            print("SUCCESS: Schema Violation Path (No plan created)")

if __name__ == "__main__":
    asyncio.run(run_integration_test())
