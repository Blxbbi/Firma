import unittest
import os
import shutil
import tempfile
import uuid
import asyncio
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from engine.models import Base, Plan, Task, Message, MessageHeader, MessageType
from engine.repository import MessageRepository
from engine.workflow import process_task_message, execute_submitted_task
from engine.services.sandbox import LocalSandbox
from unittest.mock import patch

class TestPhase2Execution(unittest.TestCase):
    def setUp(self):
        # 1. DB Setup
        self.db_file = f"test_phase2_{uuid.uuid4()}.db"
        self.engine = create_engine(f"sqlite:///{self.db_file}")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.session = self.Session()
        self.repo = MessageRepository(self.session)

        # 2. Filesystem Setup
        self.test_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.test_dir.name)
        
        # 3. Sandbox Setup
        self.sandbox_dir = tempfile.TemporaryDirectory()
        self.sandbox = LocalSandbox(base_workdir=self.sandbox_dir.name)

        # 4. Domain Setup
        self.plan_id = "p2-plan"
        self.task_id = "T2"
        plan = Plan(id=self.plan_id, name="Phase 2 Plan", status="PLANNED")
        self.session.add(plan)
        task = Task(
            id=self.task_id, 
            plan_id=self.plan_id, 
            state="IN_PROGRESS",
            expected_artifacts=[],
            acceptance_criteria=[]
        )
        self.session.add(task)
        self.session.commit()

    def tearDown(self):
        self.session.close()
        # Handle Windows file locking: try to remove, but ignore if locked
        if hasattr(self, 'db_file') and os.path.exists(self.db_file):
            try:
                os.remove(self.db_file)
            except OSError:
                pass
        self.test_dir.cleanup()
        self.sandbox_dir.cleanup()

    def _create_result_msg(self, artifacts):
        return Message(
            header=MessageHeader(
                message_id=str(uuid.uuid4()),
                sender="worker",
                recipient="engine",
                message_type=MessageType.TASK_RESULT,
                plan_id=self.plan_id
            ),
            payload={"artifacts": artifacts}
        )

    def test_full_cycle_submitted_to_verified(self):
        """
        Tests the complete Phase 2 flow:
        TASK_RESULT -> SUBMITTED -> Execution -> VALIDATION_RESULT -> VERIFIED
        """
        print("\n--- Running test_full_cycle_submitted_to_verified ---")
        # 1. Submit Task Result
        code = "print('Hello from Reality')"
        msg = self._create_result_msg([{"path": "main.py", "content": code, "action": "CREATE"}])
        
        with patch.dict(os.environ, {"FIRMA_ARTIFACT_STORE_DIR": str(self.base_path)}):
            res = process_task_message(self.session, msg, self.task_id, MessageType.TASK_RESULT)
            print(f"Submission passed: {res.passed}")
            self.assertTrue(res.passed)
            self.assertEqual(self.repo.get_task(self.task_id).state, "SUBMITTED")

        # 2. Trigger Execution
        print("Triggering execution...")
        res_val = asyncio.run(
            execute_submitted_task(self.session, self.sandbox, self.task_id, self.plan_id)
        )
        print(f"Execution workflow passed: {res_val.passed}")
        self.assertTrue(res_val.passed)
        
        # 3. Verify Final State
        final_task = self.repo.get_task(self.task_id)
        print(f"Final State: {final_task.state}")
        self.assertEqual(final_task.state, "VERIFIED")

    def test_integrity_failure_missing_file(self):
        """
        Tests that if a file exists in DB but is deleted from disk, execution fails.
        """
        print("\n--- Running test_integrity_failure_missing_file ---")
        # 1. Submit
        msg = self._create_result_msg([{"path": "main.py", "content": "print(1)", "action": "CREATE"}])
        with patch.dict(os.environ, {"FIRMA_ARTIFACT_STORE_DIR": str(self.base_path)}):
            process_task_message(self.session, msg, self.task_id, MessageType.TASK_RESULT)
        
        # 2. Sabotage: Delete the file from the artifact store
        file_path = self.base_path / self.plan_id / self.task_id / "main.py"
        os.remove(file_path)
        print(f"Deleted file: {file_path}")
        
        # 3. Trigger Execution
        asyncio.run(
            execute_submitted_task(self.session, self.sandbox, self.task_id, self.plan_id)
        )
        
        final_task = self.repo.get_task(self.task_id)
        print(f"Final State after sabotage: {final_task.state}")
        # Should not be VERIFIED
        self.assertNotEqual(final_task.state, "VERIFIED")
        self.assertEqual(final_task.state, "READY")

if __name__ == "__main__":
    unittest.main()
