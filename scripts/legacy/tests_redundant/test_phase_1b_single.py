import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from nats.aio.client import Client as NATS

from engine.db import DatabaseManager
from engine.models import Base, Task, ExecutionPhase, AssignedRole
from engine.repository import MessageRepository
from engine.transport.pimessenger import PiMessengerTransport
from engine.orchestrator import Orchestrator
from unittest.mock import MagicMock

# Logging Configuration
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler("kernel_phase1b.log", mode='w'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("Phase1B-Kernel")

async def setup_nats_clean():
    """Resets NATS environment for a clean Phase 1B run."""
    logger.info("Resetting NATS environment...")
    nc = NATS()
    await nc.connect("nats://localhost:4222")
    js = nc.jetstream()

    for stream in ["TASKS", "RESPONSES"]:
        try:
            await js.delete_stream(stream)
        except Exception:
            pass

    await js.add_stream(name="TASKS", subjects=["tasks.*"], retention="workqueue", storage="file", num_replicas=1)
    await js.add_stream(name="RESPONSES", subjects=["kernel.responses"], retention="workqueue", storage="file", num_replicas=1)
    await js.add_consumer(stream="RESPONSES", durable_name="kernel-consumer", ack_policy="explicit", ack_wait=30, max_deliver=10)
    
    await nc.close()
    logger.info("NATS Reset Complete.")

async def run_phase_1b():
    task_id = "T-B1-01"
    db_path = "mesh_phase1b.db"
    worker_log = "worker_phase1b.log"
    
    # Cleanup previous DB
    if os.path.exists(db_path):
        os.remove(db_path)

    await setup_nats_clean()
    
    db_manager = DatabaseManager(f"sqlite:///{db_path}")
    Base.metadata.create_all(db_manager.engine)
    
    # 1. Kernel Setup
    transport = PiMessengerTransport(sender_id="kernel-01")
    await transport.connect()
    
    scheduler = MagicMock()
    scheduler.run_tick = MagicMock()
    scheduler.assign_unassigned_ready_tasks = MagicMock()
    
    orchestrator = Orchestrator(
        db_manager=db_manager,
        scheduler=scheduler,
        transport=transport,
        execution_service=MagicMock(),
        sandbox=MagicMock()
    )

    # 2. Inject Task
    with db_manager.session_scope() as session:
        from engine.models import Project, Plan
        project = Project(id="P-B1", name="Phase 1B Project")
        session.add(project)
        session.flush()
        plan = Plan(id="PL-B1", project_id=project.id, version=1, name="B1 Plan", status="IN_PROGRESS")
        session.add(plan)
        session.flush()
        project.active_plan_id = plan.id
        task = Task(
            id=task_id,
            plan_id=plan.id,
            description="Phase 1B Boundary Test",
            state="READY",
            execution_phase=ExecutionPhase.CODING,
            assigned_role=AssignedRole.CODER,
            state_revision=0,
            expected_artifacts=[],
            acceptance_criteria=[]
        )
        session.add(task)
        session.commit()
    logger.info(f"Task {task_id} injected into DB.")

    # 3. Spawn Worker (External Process)
    logger.info("Spawning external worker process...")
    with open(worker_log, "w") as f:
        worker_proc = subprocess.Popen(
            [sys.executable, "pi_worker_minimal.py"],
            stdout=f,
            stderr=f,
            text=True
        )
    
    try:
        # 4. Dispatch
        logger.info("Dispatching Task...")
        dispatch_payload = {
            "task_id": task_id,
            "assigned_role": "CODER",
            "execution_phase": ExecutionPhase.CODING,
            "state_revision": 0,
            "context": {}
        }
        await transport.dispatch(dispatch_payload)
        
        # Wait for worker to finish his one task and exit
        logger.info("Waiting for worker to process and exit...")
        try:
            exit_code = worker_proc.wait(timeout=15)
            logger.info(f"Worker exited with code {exit_code}")
        except subprocess.TimeoutExpired:
            logger.error("Worker timed out! Terminating...")
            worker_proc.terminate()
            exit_code = worker_proc.wait()
            logger.info(f"Worker terminated. Exit code: {exit_code}")

        # 5. Kernel Poll & Process
        logger.info("Kernel polling for response...")
        await orchestrator.tick()
        
        # 6. Verify DB state
        with db_manager.session_scope() as session:
            repo = MessageRepository()
            task = repo.get_task_by_id(session, task_id)
            final_phase = task.execution_phase
            final_rev = task.state_revision
            logger.info(f"Final state: Phase={final_phase}, Rev={final_rev}")
        
        if final_phase == ExecutionPhase.VERIFYING and final_rev == 1:
            logger.info("✅ PHASE 1B SUCCESS: Boundary crossing verified.")
        else:
            logger.error(f"❌ PHASE 1B FAILURE: Unexpected state Phase={final_phase}, Rev={final_rev}")

    finally:
        await transport.close()
        if worker_proc.poll() is None:
            worker_proc.kill()

async def main():
    try:
        await run_phase_1b()
    except Exception as e:
        logger.exception(f"Critical Failure in Phase 1B: {e}")

if __name__ == "__main__":
    asyncio.run(main())
