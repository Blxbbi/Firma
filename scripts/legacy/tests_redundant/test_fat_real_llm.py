import asyncio
import json
import os
import uuid
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Tuple

from engine.db import DatabaseManager
from engine.models import Base, Task, ExecutionPhase, AssignedRole, Project, Plan, FileAction
from engine.repository import MessageRepository
from engine.orchestrator import Orchestrator
from engine.services.artifact_store import ArtifactStore
from engine.transport.pimessenger import PiMessengerTransport
from engine.services.execution import ExecutionService
from engine.services.sandbox import LocalPythonSandbox

# Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] FAT-RealLLM: %(message)s'
)
logger = logging.getLogger("FAT-RealLLM")

class SimpleScheduler:
    """
    A minimal scheduler that dispatches READY tasks to the Mesh.
    Zero-Logic: If it's READY, send it to the corresponding Worker subject.
    """
    def __init__(self, db_manager: DatabaseManager, transport: PiMessengerTransport):
        self.db = db_manager
        self.transport = transport

    async def assign_unassigned_ready_tasks(self):
        """
        Scans DB for READY tasks and dispatches them via Transport.
        """
        with self.db.session_scope() as session:
            from engine.repository import MessageRepository
            repo = MessageRepository()
            
            # Find tasks in READY state
            ready_tasks = session.query(Task).filter(Task.state == "READY").all()
            
            for task in ready_tasks:
                logger.info(f"[Scheduler] Dispatching Task {task.id} ({task.assigned_role}) to Mesh...")
                
                payload = {
                    "task_id": task.id,
                    "assigned_role": task.assigned_role,
                    "execution_phase": task.execution_phase,
                    "state_revision": task.state_revision,
                    "description": task.description,
                    "acceptance_criteria": task.acceptance_criteria,
                    "existing_artifacts": [],
                }
                
                try:
                    await self.transport.dispatch(payload)
                    # Mark as CLAIMED so we don't dispatch it every tick
                    task.state = "CLAIMED"
                    session.commit()
                    logger.info(f"[Scheduler] Task {task.id} dispatched and marked as CLAIMED.")
                except Exception as e:
                    logger.error(f"[Scheduler] Failed to dispatch {task.id}: {e}")

class FATRealLLMHarness:
    def __init__(self):
        import time
        self.db_url = f"sqlite:///fat_real_llm_{int(time.time())}.db"
        self.db_manager = DatabaseManager(self.db_url)
        self.transport = PiMessengerTransport(nats_url="nats://localhost:4222")
        self.execution_service = ExecutionService(sandbox=LocalPythonSandbox())
        
        # Use the SimpleScheduler to ensure tasks actually go to NATS
        self.scheduler = SimpleScheduler(self.db_manager, self.transport)
        
        self.orchestrator = Orchestrator(
            db_manager=self.db_manager,
            scheduler=self.scheduler,
            transport=self.transport,
            execution_service=self.execution_service,
            sandbox=LocalPythonSandbox()
        )

    async def setup_env(self):
        Base.metadata.create_all(self.db_manager.engine)
        await self.transport.connect()

    async def teardown_env(self):
        await self.transport.close()

    async def create_fat_task(self) -> str:
        """Creates the Prime-Sum task."""
        task_id = "T-FAT-01"
        with self.db_manager.session_scope() as session:
            p_id = "P-FAT-01"
            pl_id = "PL-FAT-01"
            project = Project(id=p_id, name="FAT Project")
            session.add(project)
            session.flush()
            plan = Plan(id=pl_id, project_id=project.id, version=1, name="FAT Plan", status="IN_PROGRESS")
            session.add(plan)
            session.flush()
            project.active_plan_id = plan.id
            session.flush()
            
            task = Task(
                id=task_id,
                plan_id=plan.id,
                state="READY",
                execution_phase=ExecutionPhase.CODING,
                assigned_role=AssignedRole.CODER,
                state_revision=0,
                expected_artifacts=[{"path": "main.py", "type": FileAction.CREATE}],
                acceptance_criteria=[
                    "sum_primes(0) == 0",
                    "sum_primes(1) == 0",
                    "sum_primes(2) == 2",
                    "sum_primes(10) == 17"
                ]
            )
            session.add(task)
            session.flush()
        return task_id

    async def run_fat_loop(self):
        task_id = await self.create_fat_task()
        logger.info(f"🚀 Starting Mesh-Compliant FAT Loop for {task_id}...")
        
        while True:
            # Tick Orchestrator (handles verification, dispatch via scheduler, and poll)
            await self.orchestrator.tick()
            
            with self.db_manager.session_scope() as session:
                repo = MessageRepository()
                task = repo.get_task_by_id(session, task_id)
                
                logger.info(f"Task Status: Phase={task.execution_phase}, Rev={task.state_revision}, Attempts={task.attempt_count}, State={task.state}")
                
                if task.execution_phase == ExecutionPhase.COMPLETE:
                    logger.info("✅ FAT SUCCESS: Task reached COMPLETE phase.")
                    return True
                
                if task.execution_phase == ExecutionPhase.FAILED_ITERATION_LIMIT:
                    logger.error("❌ FAT FAILURE: Iteration limit reached.")
                    return False
                
                if task.state == "FAILED":
                    logger.error("❌ FAT FAILURE: Task entered FAILED state.")
                    return False
            
            await asyncio.sleep(1.0)

async def main():
    harness = FATRealLLMHarness()
    await harness.setup_env()
    try:
        success = await harness.run_fat_loop()
        if success:
            logger.info("🏁 FAT PASSED: System successfully handled the real-LLM loop over NATS.")
        else:
            logger.error("🏁 FAT FAILED: System failed to converge or hit limits.")
    finally:
        await harness.teardown_env()

if __name__ == "__main__":
    asyncio.run(main())
