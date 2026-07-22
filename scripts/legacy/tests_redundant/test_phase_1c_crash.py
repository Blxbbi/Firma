import asyncio
import logging
import os
import subprocess
import sys
from nats.aio.client import Client as NATS

from engine.db import DatabaseManager
from engine.models import Base, Task, ExecutionPhase, AssignedRole
from engine.repository import MessageRepository

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger("Phase1C")

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
        return task.execution_phase, task.state_revision

async def run_scenario_s1():
    """S1: Worker crash pre-publish."""
    logger.info("--- SCENARIO S1: Worker Crash Pre-Publish ---")
    task_id = "T-S1"
    await setup_nats_clean()
    
    db_manager = DatabaseManager("sqlite:///mesh_crash_test.db")
    Base.metadata.create_all(db_manager.engine)
    
    with db_manager.session_scope() as session:
        from engine.models import Project, Plan
        project = Project(id="P-S1", name="S1 Project")
        session.add(project)
        session.flush()
        plan = Plan(id="PL-S1", project_id=project.id, version=1, name="S1 Plan", status="IN_PROGRESS")
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
    
    # Spawn Faulty Worker
    with open("worker_s1.log", "w") as f:
        worker = subprocess.Popen([sys.executable, "pi_worker_faulty.py", "--fault", "crash_pre_publish"], stdout=f, stderr=f)
    
    worker.wait(timeout=10)
    logger.info(f"Worker exited with code {worker.returncode}")
    
    phase, rev = await get_task_state(task_id)
    logger.info(f"State after crash: Phase={phase}, Rev={rev}")
    
    # Recovery: Start Healthy Worker
    logger.info("Starting healthy worker for recovery...")
    with open("worker_s1_rec.log", "w") as f:
        worker_rec = subprocess.Popen([sys.executable, "pi_worker_faulty.py", "--fault", "none"], stdout=f, stderr=f)
    
    # JetStream redelivery occurs after AckWait (configured to 30s in setup_nats_clean)
    logger.info("Waiting for JetStream redelivery (AckWait)...")
    await asyncio.sleep(32) 
    
    from engine.orchestrator import Orchestrator
    from unittest.mock import MagicMock
    orchestrator = Orchestrator(db_manager, MagicMock(), transport, MagicMock(), MagicMock())
    
    await orchestrator.tick()
    
    phase, rev = await get_task_state(task_id)
    logger.info(f"Final State: Phase={phase}, Rev={rev}")
    
    worker_rec.wait(timeout=10)
    await transport.close()
    
    if phase == ExecutionPhase.VERIFYING and rev == 1:
        logger.info("✅ S1 SUCCESS")
    else:
        logger.error("❌ S1 FAILURE")

async def main():
    await run_scenario_s1()

if __name__ == "__main__":
    asyncio.run(main())
