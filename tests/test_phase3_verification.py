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

class TestPhase3Verification(unittest.TestCase):
    def setUp(self):
        self.db_file = f"test_phase3_{uuid.uuid4()}.db"
        self.engine = create_engine(f"sqlite:///{self.db_file}")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.session = self.Session()
        self.repo = MessageRepository(self.session)

        self.test_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.test_dir.name)
        
        self.sandbox_dir = tempfile.TemporaryDirectory()
        self.sandbox = LocalSandbox(base_workdir=self.sandbox_dir.name)

        self.plan_id = "p3-plan"
        self.task_id = "T3"
        plan = Plan(id=self.plan_id, name="Phase 3 Plan", status="PLANNED")
        self.session.add(plan)
        
    def tearDown(self):
        self.session.close()
        if os.path.exists(self.db_file):
            try: os.remove(self.db_file)
            except: pass
        self.test_dir.cleanup()
        self.sandbox_dir.cleanup()

    def _create_task(self, criteria):
        task = Task(
            id=self.task_id, 
            plan_id=self.plan_id, 
            state="IN_PROGRESS",
            expected_artifacts=[],
            acceptance_criteria=criteria
        )
        self.session.add(task)
        self.session.commit()
        return task

    def _submit_code(self, code):
        msg = Message(
            header=MessageHeader(
                message_id=str(uuid.uuid4()),
                sender="worker",
                recipient="engine",
                message_type=MessageType.TASK_RESULT,
                plan_id=self.plan_id
            ),
            payload={"artifacts": [{"path": "main.py", "content": code, "action": "CREATE"}]}
        )
        with patch.dict(os.environ, {"FIRMA_ARTIFACT_STORE_DIR": str(self.base_path)}):
            process_task_message(self.session, msg, self.task_id, MessageType.TASK_RESULT)

    def test_exit_0_but_wrong_output(self):
        """✅ Exit Code 0 + falscher Output -> FAILED"""
        self._create_task(["CMD:python main.py:Expected Hello"])
        self._submit_code("print('Wrong Hello')")
        
        asyncio.run(execute_submitted_task(self.session, self.sandbox, self.task_id, self.plan_id))
        
        self.assertEqual(self.repo.get_task(self.task_id).state, "READY")

    def test_exit_0_but_missing_file(self):
        """✅ Exit Code 0 + fehlende Datei -> FAILED"""
        self._create_task(["EXISTS:output.txt"])
        self._submit_code("print('Success')") # Doesn't create output.txt
        
        asyncio.run(execute_submitted_task(self.session, self.sandbox, self.task_id, self.plan_id))
        
        self.assertEqual(self.repo.get_task(self.task_id).state, "READY")

    def test_exact_match_success(self):
        """✅ Exit Code 0 + exakter Match -> VERIFIED"""
        self._create_task(["CMD:python main.py:Hello World"])
        self._submit_code("print('Hello World')")
        
        asyncio.run(execute_submitted_task(self.session, self.sandbox, self.task_id, self.plan_id))
        
        self.assertEqual(self.repo.get_task(self.task_id).state, "VERIFIED")

    def test_multiple_criteria_partial_fail(self):
        """✅ Mehrere Criteria -> alle müssen PASS sein"""
        # One passes, one fails
        self._create_task(["EXISTS:main.py", "CMD:python main.py:Wrong"])
        self._submit_code("print('Right')")
        
        asyncio.run(execute_submitted_task(self.session, self.sandbox, self.task_id, self.plan_id))
        
        self.assertEqual(self.repo.get_task(self.task_id).state, "READY")

    def test_multiple_criteria_all_pass(self):
        """✅ Multiple Criteria all pass -> VERIFIED"""
        self._create_task(["EXISTS:main.py", "CMD:python main.py:Success"])
        self._submit_code("with open('main.py', 'w') as f: f.write('print(\"Success\")')\nprint('Success')")
        # Wait, the worker already creates main.py via TASK_RESULT.
        # Let's just submit a simple print.
        self.session.delete(self.repo.get_task(self.task_id))
        self.session.commit()
        self._create_task(["EXISTS:main.py", "CMD:python main.py:Success"])
        self._submit_code("print('Success')")
        
        asyncio.run(execute_submitted_task(self.session, self.sandbox, self.task_id, self.plan_id))
        
        self.assertEqual(self.repo.get_task(self.task_id).state, "VERIFIED")

if __name__ == "__main__":
    unittest.main()
