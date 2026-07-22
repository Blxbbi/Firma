import unittest
import sys
import os
from pathlib import Path

# Add root directory to sys.path to allow imports from 'engine'
sys.path.append(str(Path(__file__).parent.parent))

from unittest.mock import MagicMock, patch
from sqlalchemy.orm import Session
from engine.services.guardian import GuardianPipeline
from engine.services.artifact_store import ArtifactStore
from engine.models import WorkerResponse, Task, Plan, ExecutionPhase, AssignedRole, TaskEvent, FileAction
from engine.governance import GovernanceMatrix
import uuid
from datetime import datetime

class TestArtifactContract(unittest.TestCase):
    def setUp(self):
        self.mock_session = MagicMock(spec=Session)
        self.mock_artifact_store = MagicMock(spec=ArtifactStore)
        self.guardian = GuardianPipeline(self.mock_artifact_store)
        
        self.plan = MagicMock(spec=Plan)
        self.plan.project_id = "proj-123"
        self.plan.version = 1
        
        self.task = MagicMock(spec=Task)
        self.task.id = "T1"
        self.task.plan = self.plan
        self.task.execution_phase = ExecutionPhase.CODING.value
        self.task.assigned_role = AssignedRole.CODER.value
        self.task.state_revision = 1
        self.task.attempt_count = 0
        
        self.mock_session.query.return_value.filter.return_value.first.return_value = self.task

    def create_payload(self, event=TaskEvent.CODE_SUBMITTED, artifacts=None, path="main.py", content="print(1)", action=FileAction.CREATE):
        if artifacts is None:
            artifacts = {"files": [{"path": path, "content": content, "action": action}]}
        
        return {
            "protocol_version": "1.0",
            "message_id": str(uuid.uuid4()),
            "task_id": "T1",
            "state_revision": 1,
            "event": event,
            "sender_role": AssignedRole.CODER.value,
            "artifacts": artifacts,
            "timestamp": datetime.utcnow().isoformat(),
            "logs": "Test logs"
        }

    def run_guardian(self, payload):
        with patch('engine.repository.MessageRepository.is_message_processed', return_value=False), \
             patch('engine.repository.MessageRepository.transition_task_atomic', return_value=True), \
             patch('engine.repository.MessageRepository.mark_message_processed', return_value=True):
            return self.guardian.process_response(self.mock_session, payload)

    def test_scenario_a_perfect_submission(self):
        payload = self.create_payload()
        success, message = self.run_guardian(payload)
        self.assertTrue(success)
        self.assertEqual(message, "SUCCESS")
        self.mock_artifact_store.persist_artifacts.assert_called_once()

    def test_scenario_b_empty_artifacts(self):
        payload = self.create_payload(artifacts={"files": []})
        success, message = self.run_guardian(payload)
        self.assertTrue(success)
        self.assertIn("SCHEMA_INVALID_TRANSITIONED", message)
        self.assertIn("EMPTY_ARTIFACT_LIST", message)
        self.mock_artifact_store.persist_artifacts.assert_not_called()

    def test_scenario_c_path_injection(self):
        payload = self.create_payload(path="../etc/passwd")
        success, message = self.run_guardian(payload)
        self.assertTrue(success)
        self.assertIn("SCHEMA_INVALID_TRANSITIONED", message)
        self.assertIn("INVALID_PATH", message)
        self.mock_artifact_store.persist_artifacts.assert_not_called()

    def test_scenario_d_absolute_path(self):
        payload = self.create_payload(path="/tmp/test.py")
        success, message = self.run_guardian(payload)
        self.assertTrue(success)
        self.assertIn("SCHEMA_INVALID_TRANSITIONED", message)
        self.assertIn("INVALID_PATH", message)

    def test_scenario_e_missing_content_for_create(self):
        payload = self.create_payload(artifacts={"files": [{"path": "main.py", "action": "CREATE"}]})
        success, message = self.run_guardian(payload)
        self.assertTrue(success)
        self.assertIn("SCHEMA_INVALID_TRANSITIONED", message)
        self.assertIn("MISSING_OR_INVALID_CONTENT", message)

    def test_scenario_f_delete_with_content(self):
        payload = self.create_payload(action=FileAction.DELETE, content="should not be here")
        success, message = self.run_guardian(payload)
        self.assertTrue(success)
        self.assertIn("SCHEMA_INVALID_TRANSITIONED", message)
        self.assertIn("DELETE_SHOULD_NOT_HAVE_CONTENT", message)

if __name__ == "__main__":
    unittest.main()
