import asyncio
import json
import os
import shutil
import uuid
import logging
import subprocess
from datetime import datetime, timezone
from typing import List, Dict, Any, Tuple

from nats.aio.client import Client as NATS
from engine.db import DatabaseManager
from engine.models import Base, Task, ExecutionPhase, AssignedRole, TaskTransitionLog, Project, Plan, FileAction
from engine.repository import MessageRepository
from engine.orchestrator import Orchestrator
from engine.services.artifact_store import ArtifactStore
from engine.transport.pimessenger import PiMessengerTransport
from engine.services.execution import ExecutionService
from engine.services.sandbox import LocalPythonSandbox

# Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] 3B-SandboxTest: %(message)s'
)
logger = logging.getLogger("SandboxTest")

class SandboxTestHarness:
    def __init__(self):
        self.db_url = "sqlite:///test_sandbox_3b.db"
        self.db_manager = DatabaseManager(self.db_url)
        self.transport = PiMessengerTransport(nats_url="nats://localhost:4222")
        self.execution_service = ExecutionService(sandbox=LocalPythonSandbox())
        
        # Orchestrator Setup
        class MockScheduler:
            def assign_unassigned_ready_tasks(self): pass
        
        self.orchestrator = Orchestrator(
            db_manager=self.db_manager,
            scheduler=MockScheduler(),
            transport=self.transport,
            execution_service=self.execution_service,
            sandbox=LocalPythonSandbox()
        )
        self.orchestrator_task = None

    async def setup_env(self):
        """Resets DB and connects Transport."""
        if os.path.exists("test_sandbox_3b.db"):
            try:
                os.remove("test_sandbox_3b.db")
            except PermissionError:
                pass
        
        Base.metadata.create_all(self.db_manager.engine)
        await self.transport.connect()
        
        # DETERMINISTIC MODE: No background run_forever() task.
        # We use manual tick() calls in run_test to control execution exactly.
        self.orchestrator_task = None
        await asyncio.sleep(0.1)

    async def teardown_env(self):
        """Cleans up Orchestrator and Transport."""
        if self.orchestrator_task:
            self.orchestrator_task.cancel()
        await self.transport.close()

    async def create_verify_task(self, artifacts: List[Dict[str, str]]) -> str:
        """Creates a task directly in the VERIFYING phase with specific artifacts."""
        task_id = f"T-SBX-{uuid.uuid4().hex[:6]}"
        with self.db_manager.session_scope() as session:
            p_id = f"P-SBX-{uuid.uuid4().hex[:6]}"
            pl_id = f"PL-SBX-{uuid.uuid4().hex[:6]}"
            project = Project(id=p_id, name="Sandbox Test Project")
            session.add(project)
            session.flush()
            plan = Plan(id=pl_id, project_id=project.id, version=1, name="SBX Plan", status="IN_PROGRESS")
            session.add(plan)
            session.flush()
            project.active_plan_id = plan.id
            session.flush()
            
            # 1. Create task FIRST (required for save_artifact guard check)
            task = Task(
                id=task_id,
                plan_id=plan.id,
                state="SUBMITTED",
                execution_phase=ExecutionPhase.VERIFYING,
                assigned_role=AssignedRole.SYSTEM,
                state_revision=1,
                expected_artifacts=[],
                acceptance_criteria=[]
            )
            session.add(task)
            session.flush()  # Ensure task is visible to save_artifact queries
            
            # 2. Then persist artifacts (task must exist in DB for save_artifact to validate)
            # Inject FileAction.CREATE into dicts if missing
            for art in artifacts:
                if 'action' not in art:
                    art['action'] = FileAction.CREATE
            
            store = ArtifactStore()
            success = store.persist_artifacts(session, project.id, plan.version, task_id, artifacts)
            if not success:
                raise RuntimeError("Artifact persistence failed during test setup")
        return task_id

    def check_zombies(self):
        """Checks for lingering python processes that are not the current test process."""
        # Use pgrep -f to find python processes. This is OS dependent.
        # For Windows, we check tasklist.
        try:
            # This is a naive check. In a real CI, we'd use psutil.
            # We look for processes containing 'python' but not this specific script.
            output = subprocess.check_output(["tasklist"], encoding="utf-8")
            # If we see multiple python processes, we might have zombies.
            # But since we are running this in a harness, we just log it.
            # For this test, we will rely on the 'LocalPythonSandbox' killing processes.
            return True # Placeholder
        except Exception:
            return False

    def check_fs_leak(self):
        """Checks for specific files that would indicate a sandbox escape."""
        # The sandbox should NEVER write to the project root or its parents.
        # We check specifically for files the test matrix tries to create via escapes.
        leaks = []
        suspicious_files = ["escape.txt", "leak.txt"]
        for f in suspicious_files:
            if os.path.exists(f):
                leaks.append(f)
        return leaks

    async def run_test(self, name: str, artifacts: List[Dict[str, str]], expected_event: str):
        logger.info(f"\n🚀 Testing {name}...")
        
        task_id = await self.create_verify_task(artifacts)
        
        # Trigger Orchestrator tick to handle verification
        await self.orchestrator.tick()
        await asyncio.sleep(1) # Give it time to process
        
        with self.db_manager.session_scope() as session:
            repo = MessageRepository()
            task = repo.get_task_by_id(session, task_id)
            
            # Verify Transition
            current_phase = task.execution_phase
            rev = task.state_revision
            
            # Check if the event happened
            logs = session.query(TaskTransitionLog).filter(TaskTransitionLog.task_id == task_id).all()
            last_event = logs[-1].event if logs else "NONE"
            
            logger.info(f"Result: Phase={current_phase}, Rev={rev}, LastEvent={last_event}")
            
            if last_event == expected_event:
                logger.info(f"✅ {name}: PASSED")
            else:
                logger.error(f"❌ {name}: FAILED. Expected {expected_event}, got {last_event}")
                return False
        
        # Post-run audits
        leaks = self.check_fs_leak()
        if leaks:
            logger.error(f"❌ {name}: FS LEAK detected: {leaks}")
            return False
            
        return True

async def main():
    harness = SandboxTestHarness()
    await harness.setup_env()
    
    test_matrix = [
        # A. Deterministische Funktion
        ("A1-Success", [{"path": "main.py", "content": "print('OK')"}] , "VERIFY_SUCCESS"),
        ("A2-Exception", [{"path": "main.py", "content": "raise Exception('Crash')"}] , "VERIFY_FAILURE"),
        ("A3-SyntaxError", [{"path": "main.py", "content": "def x("}] , "VERIFY_FAILURE"),
        ("A4-Timeout", [{"path": "main.py", "content": "import time; time.sleep(10)"}] , "VERIFY_FAILURE"),
        
        # B. Filesystem & Escape
        ("B1-InternalWrite", [{"path": "main.py", "content": "open('test.txt', 'w').write('hi')"}] , "VERIFY_SUCCESS"),
        ("B2-EscapeWrite", [{"path": "main.py", "content": "import os; open('../escape.txt', 'w').write('hi')"}] , "VERIFY_FAILURE"),
        ("B3-Chdir", [{"path": "main.py", "content": "import os; os.chdir('..')"}] , "VERIFY_SUCCESS"),
        ("B4-RootList", [{"path": "main.py", "content": "import os; print(os.listdir('/'))"}] , "VERIFY_SUCCESS"),
        
        # C. Resource & Stability
        ("C1-Memory", [{"path": "main.py", "content": "x = 'A' * 10**7"}] , "VERIFY_SUCCESS"),
        ("C2-InfiniteLoop", [{"path": "main.py", "content": "while True: pass"}] , "VERIFY_FAILURE"),
        ("C3-ExplicitExit", [{"path": "main.py", "content": "import sys; sys.exit(0)"}] , "VERIFY_SUCCESS"),
    ]
    
    results = []
    for name, arts, exp in test_matrix:
        res = await harness.run_test(name, arts, exp)
        results.append(res)
    
    await harness.teardown_env()
    
    success_rate = sum(results) / len(results) * 100
    logger.info(f"\n--- FINAL REPORT ---")
    logger.info(f"Success Rate: {success_rate:.2f}%")
    if success_rate == 100:
        logger.info("✅ ALL SANDBOX TESTS PASSED. Determinism Verified.")
    else:
        logger.error("❌ SANDBOX TESTS FAILED. Isolation compromised.")

if __name__ == "__main__":
    asyncio.run(main())
