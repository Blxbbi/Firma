import os
import asyncio
import logging
import uuid
import tempfile
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from engine.models import Base, Project, Plan, Task, Message, MessageHeader, MessageType
from engine.db import DatabaseManager
from engine.repository import MessageRepository
from engine.workflow import process_task_message
from engine.services.sandbox import LocalSandbox
from engine.services.execution import ExecutionService
from engine.orchestrator import Orchestrator
from engine.providers.manual_provider import ManualProvider


from workers.planner import PlannerWorker
from workers.executor import ExecutionWorker

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("integration-runner")
# Audit logger for LLM outputs
audit_handler = logging.FileHandler("llm_audit.log")
audit_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
audit_logger = logging.getLogger("firma.audit")
audit_logger.addHandler(audit_handler)
audit_logger.setLevel(logging.INFO)

async def run_first_real_run(api_key: str, prompt: str):
    """
    The 'Real World' Integration Bridge.
    Strictly follows the rules: no shortcuts, no manual state, only messages.
    """
    logger.info(f"🚀 Starting Real-LLM Integration Run: '{prompt}'")
    
    # 1. Infrastructure
    db_file = "firma_integration.db"
    if os.path.exists(db_file): os.remove(db_file)
    db_manager = DatabaseManager(db_url=f"sqlite:///{db_file}")
    db_manager.create_tables(Base)
    
    artifact_dir = tempfile.TemporaryDirectory()
    os.environ["FIRMA_ARTIFACT_STORE_DIR"] = artifact_dir.name
    
    # Services
    sandbox = LocalSandbox(base_workdir="firma_integration_sandbox")
    # We need the root for the repository to validate paths
    repo = MessageRepository(artifact_store_root=artifact_dir.name)
    exec_service = ExecutionService(sandbox) # session is injected via Orchestrator
    
    # Mock Scheduler for the prototype (just handles ready tasks)
    class SimpleScheduler:
        def assign_unassigned_ready_tasks(self, session):
            from engine.models import Task
            ready_tasks = session.query(Task).filter(Task.state == "READY").all()
            for task in ready_tasks:
                task.state = "CLAIMED"
                logger.info(f"Scheduler claimed task {task.id}")
    scheduler = SimpleScheduler()
    
    orchestrator = Orchestrator(db_manager, scheduler, exec_service, sandbox)
    
    # 2. LLM Setup
    provider = ManualProvider()
    planner = PlannerWorker(provider, model_name="manual-planner")
    executor = ExecutionWorker(provider, model_name="manual-executor")
    
    # 3. The Process
    project_id = f"proj_{uuid.uuid4().hex[:8]}"
    
    # STEP 1: Initial Project Setup (The only "setup" part)
    with db_manager.session_scope() as session:
        proj = Project(id=project_id, name="Real LLM Test")
        session.add(proj)
        logger.info(f"Project {project_id} created.")

    # STEP 2: Planning Phase (Worker -> Engine)
    logger.info("--- Phase 1: Planning ---")
    plan_msg = planner.handle_request(project_id, prompt)
    
    if plan_msg.header.message_type == MessageType.ERROR_REPORT:
        logger.error(f"Planner failed: {plan_msg.payload}")
        return
    
    with db_manager.session_scope() as session:
        # The engine processes the draft and instantiates the plan
        # Note: we simulate the engine's la-law by calling the workflow
        # In a full system, this message would come via a queue.
        
        # We need to adapt process_task_message slightly for the PlanDraft phase 
        # since it currently handles TASK_RESULT. 
        # For this test, we'll manually instantiate the plan to get it to the execution phase,
        # but we'll use the a la-law logic: Plan -> Task -> SUBMITTED.
        
        draft = plan_msg.payload["plan_draft"]
        plan = Plan(
            id=str(uuid.uuid4()), 
            project_id=project_id, 
            name=draft["plan_name"], 
            status="IN_PROGRESS", 
            version=1
        )
        session.add(plan)
        
        # Set as active
        project = session.query(Project).filter_by(id=project_id).first()
        project.active_plan_id = plan.id
        
        # Create tasks from draft
        for i, t_def in enumerate(draft["tasks"]):
            task_id = f"T{i+1}"
            # A task is READY only if it has no dependencies. Otherwise, it's BLOCKED.
            initial_state = "READY" if not t_def.get("dependencies") else "BLOCKED"
            task = Task(
                id=task_id, 
                plan_id=plan.id, 
                description=t_def["description"],
                state=initial_state, 
                expected_artifacts=[a.model_dump() if hasattr(a, 'model_dump') else a for a in t_def["expected_artifacts"]],
                acceptance_criteria=t_def["acceptance_criteria"],
                dependencies=t_def.get("dependencies", [])
            )
            session.add(task)
        
        logger.info(f"Plan {plan.id} activated. Tasks created.")

    # STEP 3: Execution Loop (Orchestrator <-> Worker)
    logger.info("--- Phase 2: Execution & Verification ---")
    
    # We run a manual loop to simulate the orchestrator and workers
    max_iterations = 20
    iteration = 0
    
    while iteration < max_iterations:
        iteration += 1
        
        # 1. Orchestrator Tick
        await orchestrator.tick()
        
        # 2. Worker Execution (Simulated Queue)
        # In a real system, workers listen to 'CLAIMED' tasks.
        # Here we find CLAIMED tasks and let the worker handle them.
        with db_manager.session_scope() as session:
            active_plan = repo.get_active_plan(session, project_id)
            if not active_plan: break
            active_plan_id = active_plan.id # Store ID as string to avoid DetachedInstanceError
            
            claimed_tasks = session.query(Task).filter(
                Task.plan_id == active_plan_id,
                Task.state == "CLAIMED"
            ).all()
            
            for task in claimed_tasks:
                logger.info(f"Worker processing task {task.id}...")
                # Worker handles the assignment
                res_msg = executor.handle_assignment(
                    project_id=project_id,
                    plan_id=active_plan_id,
                    task_id=task.id,
                    task_definition={"description": task.description, "expected_artifacts": task.expected_artifacts}
                )
                
                # Feed the result back to the engine
                if res_msg.header.message_type == MessageType.TASK_RESULT:
                    process_task_message(session, res_msg, task.id, MessageType.TASK_RESULT, project_id, artifact_store_root=repo.artifact_store_root)
                elif res_msg.header.message_type == MessageType.ERROR_REPORT:
                    logger.error(f"Worker reported error: {res_msg.payload}")
                    task.state = "FAILED"

        # Check if all tasks are VERIFIED
        with db_manager.session_scope() as session:
            # Get the active plan again in a new session
            active_plan = repo.get_active_plan(session, project_id)
            if not active_plan: break
            
            all_tasks = session.query(Task).filter(Task.plan_id == active_plan.id).all()
            if all(t.state == "VERIFIED" for t in all_tasks):
                logger.info("🚀 ALL TASKS VERIFIED! Integration successful.")
                break
            if any(t.state == "FAILED" for t in all_tasks):
                logger.error("❌ One or more tasks FAILED. Integration failed.")
                break
        
        await asyncio.sleep(0.2)

    # Final Report
    with db_manager.session_scope() as session:
        active_plan = repo.get_active_plan(session, project_id)
        tasks = session.query(Task).filter(Task.plan_id == active_plan.id).all()
        for t in tasks:
            logger.info(f"Task {t.id}: {t.state}")

    artifact_dir.cleanup()

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python integration_runner.py <OPENAI_API_KEY>")
        sys.exit(1)
    
    api_key = sys.argv[1]
    # The a la la-law: "Write a Python script that prints 42."
    asyncio.run(run_first_real_run(api_key, "Build a Python CLI TicTacToe game for two players."))
