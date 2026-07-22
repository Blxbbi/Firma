import asyncio
import logging
import os
import subprocess
import sys
from nats.aio.client import Client as NATS

from engine.db import DatabaseManager
from engine.models import Base, Task, ExecutionPhase, AssignedRole
from engine.repository import MessageRepository

# Logging Configuration
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler("kernel_phase1c_s3.log", mode='w'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("Phase1C-S3")

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
        from engine.models import TaskEventLog
        transitions = session.query(TaskEventLog).filter(TaskEventLog.task_id == task_id).count()
        return task.execution_phase, task.state_revision, transitions

async def run_scenario_s3():
    """S3: Kernel crash post-poll, pre-ack."""
    logger.info("--- SCENARIO S3: Kernel Crash Post-Poll, Pre-Ack ---")
    task_id = "T-S3"
    await setup_nats_clean()
    
    db_manager = DatabaseManager("sqlite:///mesh_crash_test.db")
    Base.metadata.create_all(db_manager.engine)
    
    with db_manager.session_scope() as session:
        from engine.models import Project, Plan
        project = Project(id="P-S3", name="S3 Project")
        session.add(project)
        session.flush()
        plan = Plan(id="PL-S3", project_id=project.id, version=1, name="S3 Plan", status="IN_PROGRESS")
        session.add(plan)
        session.flush()
        project.active_plan_id = plan.id
        task = Task(id=task_id, plan_id=plan.id, state="READY", execution_phase=ExecutionPhase.CODING, assigned_role=AssignedRole.CODER, state_revision=0, expected_artifacts=[], acceptance_criteria=[])
        session.add(task)
        session.commit()

    from engine.transport.pimessenger import PiMessengerTransport
    transport = PiMessengerTransport(sender_id="kernel-01")
    await transport.connect()
    await transport.dispatch({"task_id": task_id, "assigned_role": "CODER", "execution_phase": ExecutionPhase.CODING, "state_revision": 0, "context": {}})
    
    # 1. Start Healthy Worker to produce response
    logger.info("Spawning Healthy Worker to publish response...")
    with open("worker_s3.log", "w") as f:
        worker = subprocess.Popen([sys.executable, "pi_worker_faulty.py", "--fault", "none"], stdout=f, stderr=f)
    
    # Wait for worker to finish
    await asyncio.sleep(5)
    logger.info(f"Worker exited with code {worker.poll()}")
    
    # 2. Kernel Crash post-poll
    logger.info("Running Kernel with fault: crash_post_poll...")
    with open("kernel_s3_faulty.log", "w") as f:
        kernel_faulty = subprocess.Popen([sys.executable, "kernel_runner.py", "--fault", "crash_post_poll"], stdout=f, stderr=f)
    
    kernel_faulty.wait(timeout=10)
    logger.info(f"Kernel Faulty exited with code {kernel_faulty.returncode}")
    
    phase_pre, rev_pre, trans_pre = await get_task_state(task_id)
    logger.info(f"State after crash: Phase={phase_pre}, Rev={rev_pre}, Transitions={trans_pre}")
    
    # 3. Recovery: Restart Healthy Kernel
    logger.info("Waiting for JetStream redelivery (AckWait 30s)...")
    await asyncio.sleep(32)
    
    logger.info("Running Healthy Kernel for recovery...")
    with open("kernel_s3_rec.log", "w") as f:
        kernel_rec = subprocess.Popen([sys.executable, "kernel_runner.py", "--fault", "none"], stdout=f, stderr=f)
    
    kernel_rec.wait(timeout=10)
    logger.info(f"Kernel Recovery exited with code {kernel_rec.returncode}")
    
    phase_post, rev_post, trans_post = await get_task_state(task_id)
    logger.info(f"Final State: Phase={phase_post}, Rev={rev_post}, Transitions={trans_post}")
    
    await transport.close()
    
    if phase_post == ExecutionPhase.VERIFYING and rev_post == 1 and trans_post == 1:
        logger.info("✅ S3 SUCCESS: Kernel crash post-poll handled correctly.")
    else:
        logger.error(f"❌ S3 FAILURE: State={phase_post}, Rev={rev_post}, Trans={trans_post}")

async def main():
    try:
        await run_scenario_s3()
    except Exception as e:
        logger.exception(f"Critical Failure in S3: {e}")

if __name__ == "__main__":
    asyncio.run(main())
