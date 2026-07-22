import os
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from engine.db import Session, init_db
from engine.models import Message, MessageHeader, MessageType, Plan
from engine.workflow import process_message_workflow

logging.basicConfig(level=logging.INFO)

def test_end_to_end_activation():
    # 1. Setup DB
    if os.path.exists("engine.db"):
        os.remove("engine.db")
    init_db()
    
    with Session() as session:
        # 2. Simulate Engine sending PLAN_REQUEST
        # In a real system, this would go via pi-messenger
        print("\n--- [ENGINE] Sending PLAN_REQUEST ---")
        # (We simulate the worker receiving it in the next step)

        # 3. Simulate Planner Worker receiving PLAN_REQUEST and responding with PLAN_DRAFT_SUBMITTED
        print("--- [PLANNER] Received PLAN_REQUEST. Generating draft... ---")
        draft_payload = {
            "plan_name": "CRM System",
            "tasks": [
                {
                    "id": "T1",
                    "description": "Create DB Schema",
                    "dependencies": [],
                    "expected_artifacts": ["schema.sql"],
                    "acceptance_criteria": ["file exists"]
                },
                {
                    "id": "T2",
                    "description": "Implement Auth",
                    "dependencies": ["T1"],
                    "expected_artifacts": ["auth.py"],
                    "acceptance_criteria": ["contains login()"]
                }
            ]
        }

        plan_draft_msg = Message(
            header=MessageHeader(
                sender="Planner",
                recipient="Engine",
                message_type=MessageType.PLAN_DRAFT_SUBMITTED
            ),
            payload=draft_payload
        )

        # 4. Engine receives PLAN_DRAFT_SUBMITTED
        print("--- [ENGINE] Received PLAN_DRAFT_SUBMITTED. Processing... ---")
        result = process_message_workflow(session, plan_draft_msg)
        print(f"Engine processing result: {result}")

        if result.passed:
            print("\n[SUCCESS] Plan instantiated.")
            # Verify DB
            plan = session.query(Plan).filter(Plan.name == "CRM System").first()
            if plan:
                print(f"Plan found in DB: {plan.name} (ID: {plan.id})")
                print(f"Tasks in DB:")
                for t in plan.tasks:
                    print(f"  - [{t.state}] {t.id}: {t.description} (Deps: {t.dependencies})")
                
                # Verify initial states
                t1 = next(t for t in plan.tasks if t.id == "T1")
                t2 = next(t for t in plan.tasks if t.id == "T2")
                if t1.state == "READY" and t2.state == "BLOCKED":
                    print("\n[SUCCESS] Initial states (READY/BLOCKED) are correct.")
                else:
                    print(f"\n[ERROR] Incorrect initial states. T1:{t1.state}, T2:{t2.state}")
            else:
                print("\n[ERROR] Plan not found in DB!")
        else:
            print(f"\n[ERROR] Plan instantiation failed: {result.reason}")

if __name__ == "__main__":
    test_end_to_end_activation()
