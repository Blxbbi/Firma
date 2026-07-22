import os
import uuid
import asyncio
import tempfile
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from engine.models import Base, Plan, Task, Message, MessageHeader, MessageType
from engine.repository import MessageRepository
from engine.workflow import process_task_message, execute_submitted_task
from engine.services.sandbox import LocalSandbox

def run_company_test():
    # 1. Infrastructure Setup
    db_file = "company_run_1.db"
    if os.path.exists(db_file): os.remove(db_file)
    engine = create_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    repo = MessageRepository(session)
    sandbox = LocalSandbox(base_workdir="company_sandbox")
    
    # Artifact Store Setup
    artifact_dir = tempfile.TemporaryDirectory()
    os.environ["FIRMA_ARTIFACT_STORE_DIR"] = artifact_dir.name
    
    # 2. Planning (The Law)
    plan_id = "plan-mult-01"
    task_id = "T1"
    
    print("--- [PLANNING] ---")
    plan = Plan(id=plan_id, name="Multiplication Tool", status="PLANNED")
    session.add(plan)
    
    # Spezifikation: Multiply 2 * 3 = 6
    criteria = ["CMD:python main.py 2 3:6"]
    task = Task(
        id=task_id, 
        plan_id=plan_id, 
        state="READY", 
        expected_artifacts=["main.py"],
        acceptance_criteria=criteria
    )
    session.add(task)
    session.commit()
    print(f"Plan {plan_id} created. Task {task_id} created with criteria: {criteria}")

    # 3. Worker Simulation (LLM)
    print("\n--- [WORKER] ---")
    # Transition to IN_PROGRESS first (to avoid guard failure)
    task.state = "IN_PROGRESS"
    session.commit()
    
    # Worker generates a script that prints the integer result
    worker_code = """
import sys
def main():
    a = int(sys.argv[1])
    b = int(sys.argv[2])
    print(a * b)
if __name__ == "__main__":
    main()
"""
    msg = Message(
        header=MessageHeader(
            message_id=str(uuid.uuid4()),
            sender="llm-worker-1",
            recipient="engine",
            message_type=MessageType.TASK_RESULT,
            plan_id=plan_id
        ),
        payload={"artifacts": [{"path": "main.py", "content": worker_code, "action": "CREATE"}]}
    )
    
    print("Sending TASK_RESULT...")
    process_task_message(session, msg, task_id, MessageType.TASK_RESULT)
    print(f"Task state after submission: {repo.get_task(task_id).state}")

    # 4. Engine Loop (Execute & Verify)
    print("\n--- [ENGINE] ---")
    # Set log level to DEBUG to see why it fails
    import logging
    logging.basicConfig(level=logging.DEBUG)
    
    res = asyncio.run(
        execute_submitted_task(session, sandbox, task_id, plan_id)
    )
    
    final_task = repo.get_task(task_id)
    print(f"Final Task State: {final_task.state}")
    
    if final_task.state == "VERIFIED":
        print("\nSUCCESS: The system verified the reality of the code!")
    else:
        print("\nFAILURE: The system rejected the code.")
        print(f"Final State: {final_task.state}")

    session.close()
    artifact_dir.cleanup()

if __name__ == "__main__":
    run_company_test()
