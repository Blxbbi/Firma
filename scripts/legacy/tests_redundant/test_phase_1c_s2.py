import asyncio
import logging
import os
import subprocess
import sys
from nats.aio.client import Client as NATS

from engine.db import DatabaseManager
from engine.models import Base, Task, ExecutionPhase, AssignedRole
from engine.repository import MessageRepository
from engine.transport.pimessenger import PiMessengerTransport
from engine.orchestrator import Orchestrator

# Logging Configuration
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler("kernel_phase1c_s2.log", mode='w'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("Phase1C-S2")

async def setup_nats_clean():
    logger.info("Resetting NATS...")
    nc = NATS()
    await nc.connect("nats://localhost:4222")
    js = nc.jetstream()
    for stream in ["TASKS", "RESPONSES"]:
        try: await js.delete_stream(stream)
        except Exception: pass
    await js.add_stream(name="TASKS", subjects=["tasks.*"], retention="workqueue", storage="file", num_replicas=1)
    await js.add_stream(name="RESPONSES", subjects=["kernel.responses"], retention="workqueue", storage="file", num_replicas=1)
    await js.add_consumer(stream="RESPONSES", durable_name="kernel-consumer", ack_policy="explicit", ack_wait=30, max_deliver=10)
    await nc.close()

async def get_task_state(task_id):
    db_manager = DatabaseManager("sqlite:///mesh_crash_test.db")
    with db_manager.session_scope() as session:
        repo = MessageRepository()
        task = repo.get_task_by_id(session, task_id)
        # Count transitions
        from engine.models import TaskEventLog
        transitions = session.query(TaskEventLog).filter(TaskEventLog.task_id == task_id).count()
        return task.execution_phase, task.state_revision, transitions

async def run_scenario_s2():
    """S2: Worker crash post-publish, pre-ack."""
    logger.info("--- SCENARIO S2: Worker Crash Post-Publish, Pre-Ack ---")
    task_id = "T-S2"
    await setup_nats_clean()
    
    db_manager = DatabaseManager("sqlite:///mesh_crash_test.db")
    Base.metadata.create_all(db_manager.engine)
    
    with db_manager.session_scope() as session:
        from engine.models import Project, Plan
        project = Project(id="P-S2", name="S2 Project")
        session.add(project)
        session.flush()
        plan = Plan(id="PL-S2", project_id=project.id, version=1, name="S2 Plan", status="IN_PROGRESS")
        session.add(plan)
        session.flush()
        project.active_plan_id = plan.id
        task = Task(id=task_id, plan_id=plan.id, state="READY", execution_phase=ExecutionPhase.CODING, assigned_role=AssignedRole.CODER, state_revision=0, expected_artifacts=[], acceptance_criteria=[])
        session.add(task)
        session.commit()

    transport = PiMessengerTransport(sender_id="kernel-01")
    await transport.connect()
    await transport.dispatch({"task_id": task_id, "assigned_role": "CODER", "execution_phase": ExecutionPhase.CODING, "state_revision": 0, "context": {}})
    
    # 1. Spawn Faulty Worker (Crash after publish)
    logger.info("Spawning Faulty Worker (post-publish crash)...")
    with open("worker_s2_faulty.log", "w") as f:
        worker_faulty = subprocess.Popen([sys.executable, "pi_worker_faulty.py", "--fault", "crash_post_publish"], stdout=f, stderr=f)
    
    # Wait for worker to publish and crash
    await asyncio.sleep(2)
    logger.info(f"Worker Faulty exited with code {worker_faulty.poll()}")
    
    # 2. Kernel processes Response 1
    logger.info("Kernel processing Response 1...")
    from engine.orchestrator import Orchestrator
    from unittest.mock import MagicMock
    orchestrator = Orchestrator(db_manager, MagicMock(), transport, MagicMock(), MagicMock())
    await orchestrator.tick()
    
    phase_1, rev_1, trans_1 = await get_task_state(task_id)
    logger.info(f"State after Response 1: Phase={phase_1}, Rev={rev_1}, Transitions={trans_1}")
    
    # 3. Recovery: Spawn Healthy Worker
    logger.info("Spawning Healthy Worker for redelivery...")
    with open("worker_s2_rec.log", "w") as f:
        worker_rec = subprocess.Popen([sys.executable, "pi_worker_faulty.py", "--fault", "none"], stdout=f, stderr=f)
    
    # Wait for JetStream redelivery (AckWait)
    logger.info("Waiting for JetStream redelivery (AckWait)...")
    await asyncio.sleep(32) 
    
    # 4. Kernel processes Response 2 (The duplicate)
    logger.info("Kernel processing Response 2 (Duplicate)...")
    await orchestrator.tick()
    
    phase_2, rev_2, trans_2 = await get_task_state(task_id)
    logger.info(f"Final State: Phase={phase_2}, Rev={rev_2}, Transitions={trans_2}")
    
    worker_rec.wait(timeout=10)
    await transport.close()
    
    if phase_2 == ExecutionPhase.VERIFYING and rev_2 == 1 and trans_2 == 1:
        logger.info("✅ S2 SUCCESS: Idempotency verified. No duplicate transitions.")
    else:
        logger.error(f"❌ S2 FAILURE: State={phase_2}, Rev={rev_2}, Trans={trans_2}")

async def main():
    try:
        await run_scenario_s2()
    except Exception as e:
        logger.exception(f"Critical Failure in S2: {e}")

if __name__ == "__main__":
    asyncio.run(main())
