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

logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler("kernel_phase2a_race.log", mode='w'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("Phase2A-Race")

async def setup_nats_clean():
    logger.info("Resetting NATS...")
    nc = NATS()
    await nc.connect("nats://localhost:4222")
    js = nc.jetstream()
    for stream in ["TASKS", "RESPONSES"]:
        try: await js.delete_stream(stream)
        except Exception: pass
    # FOR RACE TEST: TASKS must be "limits" retention to allow multiple consumers to receive the same message
    await js.add_stream(name="TASKS", subjects=["tasks.*"], retention="limits", storage="file", num_replicas=1)
    await js.add_stream(name="RESPONSES", subjects=["kernel.responses"], retention="workqueue", storage="file", num_replicas=1)
    await js.add_consumer(stream="RESPONSES", durable_name="kernel-consumer", ack_policy="explicit", ack_wait=30, max_deliver=10)
    await nc.close()

async def get_task_state(task_id):
    db_manager = DatabaseManager("sqlite:///mesh_concurrency.db")
    with db_manager.session_scope() as session:
        repo = MessageRepository()
        task = repo.get_task_by_id(session, task_id)
        from engine.models import TaskEventLog
        transitions = session.query(TaskEventLog).filter(TaskEventLog.task_id == task_id).count()
        return task.execution_phase, task.state_revision, transitions

async def run_race_test():
    """Test 2: Forced Race Test (Unique Consumers per Worker)"""
    logger.info("--- PHASE 2A.2: FORCED RACE TEST ---")
    task_id = "T-RACE-01"
    await setup_nats_clean()
    
    db_manager = DatabaseManager("sqlite:///mesh_concurrency.db")
    Base.metadata.create_all(db_manager.engine)
    
    with db_manager.session_scope() as session:
        from engine.models import Project, Plan
        project = Project(id="P-RACE", name="Race Project")
        session.add(project)
        session.flush()
        plan = Plan(id="PL-RACE", project_id=project.id, version=1, name="Race Plan", status="IN_PROGRESS")
        session.add(plan)
        session.flush()
        project.active_plan_id = plan.id
        task = Task(id=task_id, plan_id=plan.id, state="READY", execution_phase=ExecutionPhase.CODING, assigned_role=AssignedRole.CODER, state_revision=0, expected_artifacts=[], acceptance_criteria=[])
        session.add(task)
        session.commit()

    transport = PiMessengerTransport(sender_id="kernel-01")
    await transport.connect()
    
    # Spawn 5 Workers with UNIQUE consumer names (Force race)
    workers = []
    for i in range(5):
        log_file = f"worker_race_{i}.log"
        # No consumer name provided -> unique durable created in worker
        with open(log_file, "w") as f:
            p = subprocess.Popen([sys.executable, "pi_worker_concurrency.py", "--delay", "0.1"], stdout=f, stderr=f)
            workers.append((p, log_file))
    
    logger.info("Waiting for workers to start and subscribe...")
    await asyncio.sleep(5)
    
    # Dispatch 1 Task 5 times to force a race of responses for the same task_id
    logger.info("Dispatching task 5 times to trigger forced race...")
    for i in range(5):
        await transport.dispatch({"task_id": task_id, "assigned_role": "CODER", "execution_phase": ExecutionPhase.CODING, "state_revision": 0, "context": {}})
    
    # Loop orchestrator tick until state changes or timeout
    from engine.orchestrator import Orchestrator
    from unittest.mock import MagicMock
    orchestrator = Orchestrator(db_manager, MagicMock(), transport, MagicMock(), MagicMock())
    
    logger.info("Polling for responses...")
    for _ in range(20):
        await orchestrator.tick()
        phase, rev, trans = await get_task_state(task_id)
        if rev == 1:
            break
        await asyncio.sleep(1)
    
    # Validate
    phase, rev, trans = await get_task_state(task_id)
    logger.info(f"Final State: Phase={phase}, Rev={rev}, Transitions={trans}")
    
    # Check logs to see how many workers fetched the dispatch
    fetch_count = 0
    publish_count = 0
    for p, log_file in workers:
        with open(log_file, "r") as f:
            content = f.read()
            if "fetched dispatch" in content:
                fetch_count += 1
            if "published response" in content:
                publish_count += 1
        p.terminate()
    
    logger.info(f"Workers that fetched dispatch: {fetch_count}/5")
    logger.info(f"Workers that published response: {publish_count}/5")
    
    await transport.close()
    
    if fetch_count >= 5 and rev == 1 and trans == 1:
        logger.info("✅ PHASE 2A.2 SUCCESS: Forced race handled. Exactly one winner.")
    else:
        logger.error(f"❌ PHASE 2A.2 FAILURE: fetch_count={fetch_count}, rev={rev}, trans={trans}")

if __name__ == "__main__":
    asyncio.run(run_race_test())
