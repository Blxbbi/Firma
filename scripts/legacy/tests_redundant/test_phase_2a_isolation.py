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

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger("Phase2A-Isolation")

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
    db_manager = DatabaseManager("sqlite:///mesh_concurrency.db")
    with db_manager.session_scope() as session:
        repo = MessageRepository()
        task = repo.get_task_by_id(session, task_id)
        from engine.models import TaskEventLog
        transitions = session.query(TaskEventLog).filter(TaskEventLog.task_id == task_id).count()
        return task.execution_phase, task.state_revision, transitions

async def run_isolation_test():
    """Test 1: Broker-Isolation-Test (Same Durable Consumer)"""
    logger.info("--- PHASE 2A.1: BROKER ISOLATION TEST ---")
    task_id = "T-ISO-01"
    await setup_nats_clean()
    
    db_manager = DatabaseManager("sqlite:///mesh_concurrency.db")
    Base.metadata.create_all(db_manager.engine)
    
    with db_manager.session_scope() as session:
        from engine.models import Project, Plan
        project = Project(id="P-ISO", name="Isolation Project")
        session.add(project)
        session.flush()
        plan = Plan(id="PL-ISO", project_id=project.id, version=1, name="ISO Plan", status="IN_PROGRESS")
        session.add(plan)
        session.flush()
        project.active_plan_id = plan.id
        task = Task(id=task_id, plan_id=plan.id, state="READY", execution_phase=ExecutionPhase.CODING, assigned_role=AssignedRole.CODER, state_revision=0, expected_artifacts=[], acceptance_criteria=[])
        session.add(task)
        session.commit()

    transport = PiMessengerTransport(sender_id="kernel-01")
    await transport.connect()
    
    # Spawn 5 Workers FIRST to ensure they are ready
    workers = []
    durable_name = "coder-group-isolation"
    for i in range(5):
        log_file = f"worker_iso_{i}.log"
        with open(log_file, "w") as f:
            p = subprocess.Popen([sys.executable, "pi_worker_concurrency.py", "--consumer-name", durable_name], stdout=f, stderr=f)
            workers.append((p, log_file))
    
    logger.info("Waiting for workers to start and subscribe...")
    await asyncio.sleep(5)
    
    # Dispatch 1 Task
    logger.info("Dispatching task...")
    await transport.dispatch({"task_id": task_id, "assigned_role": "CODER", "execution_phase": ExecutionPhase.CODING, "state_revision": 0, "context": {}})
    
    # Loop orchestrator tick until state changes or timeout
    from engine.orchestrator import Orchestrator
    from unittest.mock import MagicMock
    orchestrator = Orchestrator(db_manager, MagicMock(), transport, MagicMock(), MagicMock())
    
    logger.info("Polling for response...")
    success = False
    for _ in range(20):
        await orchestrator.tick()
        phase, rev, trans = await get_task_state(task_id)
        if rev == 1:
            success = True
            break
        await asyncio.sleep(1)
    
    phase, rev, trans = await get_task_state(task_id)
    logger.info(f"Final State: Phase={phase}, Rev={rev}, Transitions={trans}")
    
    # Check logs
    fetch_count = 0
    for p, log_file in workers:
        with open(log_file, "r") as f:
            if "fetched dispatch" in f.read():
                fetch_count += 1
        p.terminate()
    
    logger.info(f"Workers that fetched dispatch: {fetch_count}/5")
    await transport.close()
    
    if fetch_count == 1 and rev == 1 and trans == 1:
        logger.info("✅ PHASE 2A.1 SUCCESS: Broker isolation verified.")
    else:
        logger.error(f"❌ PHASE 2A.1 FAILURE: fetch_count={fetch_count}, rev={rev}, trans={trans}")

if __name__ == "__main__":
    asyncio.run(run_isolation_test())
