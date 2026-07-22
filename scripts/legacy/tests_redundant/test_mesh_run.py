import asyncio
import logging
import os
import subprocess
import time
import sys
from engine.db import DatabaseManager
from engine.models import Project, Plan, Task, ExecutionPhase, AssignedRole
from engine.repository import MessageRepository
from engine.orchestrator import Orchestrator
from engine.scheduler import Scheduler
from engine.services.execution import ExecutionService
from engine.services.sandbox import Sandbox
from engine.transport.pimessenger import PiMessengerTransport

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MeshTest")

async def setup_db(db_manager):
    with db_manager.session_scope() as session:
        # Create Project
        project = Project(name="Mesh Test Project")
        session.add(project)
        session.flush()

        # Create Plan
        plan = Plan(
            project_id=project.id,
            name="Mesh Test Plan",
            status="IN_PROGRESS",
            version=1
        )
        session.add(plan)
        session.flush()

        # Link project to plan
        project.active_plan_id = plan.id
        
        # Create a READY task for CODER
        task = Task(
            id="T-MESH-01",
            plan_id=plan.id,
            description="Test Mesh Dispatch",
            state="READY",
            execution_phase=ExecutionPhase.CODING.value,
            assigned_role=AssignedRole.CODER.value,
            state_revision=0,
            expected_artifacts=[],
            acceptance_criteria=[]
        )
        session.add(task)
        session.commit()
        return project.id, plan.id, task.id

async def run_test():
    # 1. Start Mock Worker
    with open("worker.log", "w") as f:
        worker_proc = subprocess.Popen([sys.executable, "mock_worker.py"], stdout=f, stderr=f)
    logger.info("Started Mock Worker process (logs to worker.log).")
    await asyncio.sleep(5) # Give worker time to connect and subscribe

    # 2. Init Engine Components
    db_manager = DatabaseManager("sqlite:///mesh_test.db")
    from engine.models import Base
    db_manager.create_tables(Base)


    project_id, plan_id, task_id = await setup_db(db_manager)
    
    # Note: We need a real scheduler and other services
    # We'll mock the scheduler to just assign our test task
    class SimpleScheduler:
        def assign_unassigned_ready_tasks(self):
            # In a real system, this would update DB state to CLAIMED
            # For the test, we'll just let the Orchestrator dispatch
            pass
        def run_tick(self):
            pass

    # Setup Transport
    transport = PiMessengerTransport()
    await transport.connect()

    # Setup Orchestrator
    # We need to provide dummy versions of some services
    orchestrator = Orchestrator(
        db_manager=db_manager,
        scheduler=SimpleScheduler(),
        transport=transport,
        execution_service=None, # Not used in tick
        sandbox=None            # Not used in tick
    )

    # To make the scheduler actually "dispatch" the task, 
    # we need to override the tick to force a dispatch of our test task.
    
    async def force_dispatch_tick():
        # 1. Force Dispatch T-MESH-01
        with db_manager.session_scope() as session:
            task = session.query(Task).filter(Task.id=="T-MESH-01").first()
            if task and task.state == "READY":
                logger.info(f"Force dispatching Task {task.id}")
                payload = {
                    "task_id": task.id,
                    "assigned_role": task.assigned_role,
                    "execution_phase": task.execution_phase,
                    "state_revision": task.state_revision,
                    "context": {"goal": "Test Mesh"},
                }
                await transport.dispatch(payload)
                task.state = "CLAIMED"
                session.commit()

        # 2. Poll and Process
        messages = await transport.poll()
        for msg in messages:
            try:
                with db_manager.session_scope() as session:
                    # Merge Envelope metadata into payload for Guardian compatibility
                    full_payload = msg.envelope["payload"].copy()
                    full_payload["message_id"] = msg.envelope.get("message_id")
                    full_payload["timestamp"] = msg.envelope.get("timestamp")
                    full_payload["protocol_version"] = msg.envelope.get("protocol_version", "1.0")
                    
                    from engine.services.guardian import GuardianPipeline
                    from engine.services.artifact_store import ArtifactStore
                    guardian = GuardianPipeline(ArtifactStore())
                    success, reason = guardian.process_response(session, full_payload)
                    logger.info(f"Guardian Decision: {success}, Reason: {reason}")
            finally:
                await msg.ack()

    logger.info("Starting roundtrip test...")
    # Run few ticks to see the dispatch and response
    for i in range(10):
        await force_dispatch_tick()
        await asyncio.sleep(1)
        
        # Check if task is now VERIFIED/COMPLETE
        with db_manager.session_scope() as session:
            task = session.query(Task).filter(Task.id=="T-MESH-01").first()
            if task and task.state == "VERIFIED":
                logger.info("SUCCESS: Task reached VERIFIED state!")
                break
    else:
        logger.error("FAILURE: Task did not reach VERIFIED state.")

    # Cleanup
    await transport.close()
    worker_proc.terminate()

if __name__ == "__main__":
    asyncio.run(run_test())
