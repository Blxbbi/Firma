import logging
import asyncio
import os
from typing import Tuple
from engine.db import DatabaseManager
from engine.models import Task, Plan, Project, Base
from engine.repository import MessageRepository
from engine.services.execution import ExecutionService
from engine.services.sandbox import LocalSandbox as Sandbox
from engine.scheduler import Scheduler
from engine.orchestrator import Orchestrator
from engine.transport import LocalTransport, ChaosTransport
from engine.worker_bridge import LocalWorkerBridge
from sqlalchemy.orm import Session

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def setup_scenario() -> Tuple[DatabaseManager, Orchestrator, LocalTransport]:
    # 1. DB Setup
    db_path_file = "chaos_test.db"
    if os.path.exists(db_path_file):
        os.remove(db_path_file)
    
    db_url = f"sqlite:///{db_path_file}"
    db_manager = DatabaseManager(db_url)
    db_manager.create_tables(Base)
    
    # 2. Components
    sandbox = Sandbox()
    exec_service = ExecutionService(sandbox)
    
    # LocalTransport needs a bridge to execute work
    # We'll define the bridge inside a function to avoid circular imports if any
    local_transport = LocalTransport()
    
    bridge = LocalWorkerBridge(db_manager, exec_service, local_transport)
    local_transport._worker_executor = bridge.handle_assignment
    
    # Wrap with Chaos
    chaos_transport = ChaosTransport(
        local_transport, 
        delay_range=(0, 0.1), 
        drop_prob=0.1, 
        dup_prob=0.2, 
        reorder_prob=0.2,
        partial_prob=0.1
    )
    
    scheduler = Scheduler(db_manager, messenger_callback=chaos_transport.dispatch)
    
    orchestrator = Orchestrator(
        db_manager=db_manager,
        scheduler=scheduler,
        transport=chaos_transport,
        execution_service=exec_service,
        sandbox=sandbox
    )
    
    # 3. Create test data
    with db_manager.session_scope() as session:
        proj = Project(id="proj_chaos", name="Chaos Project")
        session.add(proj)
        session.commit()
        
        plan = Plan(id="plan_chaos", project_id="proj_chaos", name="Chaos Plan", version=1)
        session.add(plan)
        session.commit()
        
        proj.active_plan_id = plan.id
        session.commit()
        
        # Create a sequence of 3 tasks
        t1 = Task(id="T1", plan_id="plan_chaos", state="READY", execution_phase="CODING", assigned_role="CODER", expected_artifacts=[], acceptance_criteria=[])
        t2 = Task(id="T2", plan_id="plan_chaos", state="READY", execution_phase="CODING", assigned_role="CODER", dependencies=["T1"], expected_artifacts=[], acceptance_criteria=[])
        t3 = Task(id="T3", plan_id="plan_chaos", state="READY", execution_phase="CODING", assigned_role="CODER", dependencies=["T2"], expected_artifacts=[], acceptance_criteria=[])
        session.add_all([t1, t2, t3])
        session.commit()
        
    return db_manager, orchestrator, local_transport

async def run_chaos_test():
    logger.info("Starting Chaos Transport Test...")
    db_manager, orchestrator, transport = await setup_scenario()
    
    # Run orchestrator for a few ticks
    # We want to see T1 -> T2 -> T3 complete despite chaos.
    # Since there are drops, we might need more ticks.
    for i in range(50):
        await orchestrator.tick()
        await asyncio.sleep(0.1)
        
    # Final verification
    with db_manager.session_scope() as session:
        repo = MessageRepository(session)
        tasks = session.query(Task).all()
        
        logger.info("--- Final State ---")
        for t in tasks:
            logger.info(f"Task {t.id}: State={t.state}, Phase={t.execution_phase}, Rev={t.state_revision}")
            
        # The test passes if the Kernel remains consistent.
        # Since we have drops and no retry logic yet, they might not all finish,
        # but NONE should be in an invalid state (e.g. double transition).
        
        # Check for double transitions by looking at the logs
        from engine.models import TaskTransitionLog
        logs = session.query(TaskTransitionLog).all()
        logger.info(f"Total transitions logged: {len(logs)}")
        
        # Verify monotonic revisions per task
        task_logs = {}
        for log in logs:
            task_logs.setdefault(log.task_id, []).append(log.new_revision)
            
        for tid, revs in task_logs.items():
            if revs != sorted(revs):
                raise AssertionError(f"Non-monotonic revisions for task {tid}: {revs}")

    logger.info("Chaos Test Completed. Kernel remained consistent.")

if __name__ == "__main__":
    asyncio.run(run_chaos_test())
