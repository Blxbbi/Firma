import asyncio
import os
import shutil
import logging
from engine.db import init_db, Session
from engine.models import Message, MessageHeader, MessageType, Plan, Task
from engine.repository import MessageRepository
from engine.providers.mock import MockLLMProvider, MockMode
from engine.workflow import process_message_workflow
from engine.scheduler import Scheduler
from engine.services.execution import ExecutionService
from engine.services.sandbox import LocalSandbox
from workers.planner_worker import PlannerWorker
from workers.llm_worker import LLMWorker

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

async def main():
    # 1. Setup: Fresh DB and Workspace
    if os.path.exists("engine.db"): os.remove("engine.db")
    if os.path.exists("sandbox_workspace"): shutil.rmtree("sandbox_workspace")
    init_db()
    
    # Create a single session for the orchestrator (simulation of the engine)
    with Session() as session:
        repo = MessageRepository(session)
        
        # Define the "Messenger" - the heart of the Firma
        def messenger(msg):
            logger.info(f"--- Messenger: Routing {msg.header.message_type} from {msg.header.sender} to {msg.header.recipient} ---")
            # In this simulation, we route messages directly to the workflow or workers
            if msg.header.recipient == "PlannerWorker":
                planner.handle_message(msg)
            elif msg.header.recipient in ["LLMWorker", "Worker"]:
                coder.handle_message(msg)
            else:
                # Engine handles everything else. 
                # Extract task context for task-related messages.
                task_id = msg.payload.get("task_id") if msg.payload else None
                event = msg.header.message_type if msg.header.message_type in [
                    MessageType.TASK_ACK, MessageType.TASK_RESULT, 
                    MessageType.STATUS_UPDATE, MessageType.ERROR_REPORT
                ] else None
                process_message_workflow(session, msg, task_id=task_id, event=event)

        # Initialize Workers
        provider = MockLLMProvider(MockMode.HAPPY)
        planner = PlannerWorker(messenger, provider)
        coder = LLMWorker(messenger, provider)
        
        # Initialize Scheduler and Execution Service
        scheduler = Scheduler(session, messenger_callback=messenger)
        exec_service = ExecutionService(session, LocalSandbox())

        # --- START OF FIRST REAL WORLD RUN ---
        goal = "Write a Python CLI script that adds two numbers passed as command-line arguments and prints the result."
        logger.info(f"🚀 CEO Request: {goal}")

        # 1. submit_company_task
        plan_id = "PLAN_001"
        request_msg = Message(
            header=MessageHeader(
                sender="CEO",
                recipient="PlannerWorker",
                message_type=MessageType.PLAN_REQUEST,
                plan_id=plan_id
            ),
            payload={"goal": goal}
        )
        messenger(request_msg)
        session.commit()

        # 2. Verify Plan Instantiation
        plan = session.query(Plan).first()
        if not plan:
            logger.error("FAILED: No plan was created in the database!")
            return
        logger.info(f"✅ Plan Instantiated: {plan.name} (ID: {plan.id}, Status: {plan.status})")

        # 3. Scheduler tick - Trigger Task Assignment
        logger.info("⏰ Scheduler tick...")
        scheduler.run_tick()
        session.commit()

        # 4. Verify Task Assignment
        tasks = session.query(Task).filter_by(plan_id=plan_id).all()
        for t in tasks:
            logger.info(f"Task {t.id} state: {t.state}")
            if t.state != "CLAIMED": # In our mock, the LLMWorker is instant, so it should be CLAIMED or SUBMITTED
                pass 

        # 5. Run Execution Service (The Sandbox)
        logger.info("🛠️ Running Execution Service...")
        await exec_service.process_submitted_tasks()
        session.commit()

        # 6. Final Verification
        final_tasks = session.query(Task).filter_by(plan_id=plan_id).all()
        for t in final_tasks:
            logger.info(f"FINAL STATE: Task {t.id} is {t.state}")
            if t.state == "VERIFIED":
                logger.info(f"🎉 SUCCESS: Task {t.id} is VERIFIED!")
            else:
                logger.error(f"❌ FAILURE: Task {t.id} ended in state {t.state}")

if __name__ == "__main__":
    asyncio.run(main())
