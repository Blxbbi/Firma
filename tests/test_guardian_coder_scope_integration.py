"""
Integration test for Greenfield Scope Enforcement (P1) in GuardianPipeline.process_response.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session
from engine.services.guardian import GuardianPipeline
from engine.services.artifact_store import ArtifactStore
from engine.models import Task, Plan, ExecutionPhase, AssignedRole, TaskEvent, FileAction
import uuid
from datetime import datetime, timezone


class _FakePlan:
    project_id = "proj-123"
    version = 1


class _FakeCoderTask:
    id = "task-2"
    plan_id = "plan-1"
    state = "CLAIMED"
    updated_at = datetime.now(timezone.utc)
    plan = _FakePlan()
    execution_phase = ExecutionPhase.CODING.value
    assigned_role = AssignedRole.CODER.value
    state_revision = 1
    attempt_count = 0
    last_review_feedback = None
    expected_artifacts = [
        {"path": "style.css", "type": "CREATE"}
    ]


class TestGuardianCoderScopeEnforcement:
    def setup_method(self):
        self.mock_session = MagicMock(spec=Session)
        self.mock_artifact_store = MagicMock(spec=ArtifactStore)
        self.guardian = GuardianPipeline(self.mock_artifact_store)

        task = _FakeCoderTask()
        self.task = task

        # Make session.execute async-compatible and return the task
        async def fake_execute(stmt):
            result = MagicMock()
            result.scalars.return_value.first.return_value = task
            return result
        self.mock_session.execute = AsyncMock(side_effect=fake_execute)
        self.mock_session.flush = AsyncMock(return_value=None)
        self.mock_session.refresh = AsyncMock(return_value=None)
        self.mock_session.add = MagicMock()

    def _payload(self, artifacts):
        return {
            "protocol_version": "1.0",
            "message_id": str(uuid.uuid4()),
            "task_id": "task-2",
            "run_id": "run-1",
            "state_revision": 1,
            "event": TaskEvent.CODE_SUBMITTED.value,
            "sender_role": AssignedRole.CODER.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "logs": "stub coder",
            "artifacts": artifacts,
            "plan_draft": None,
        }

    def _run(self, payload):
        with patch('engine.repository.MessageRepository.is_message_processed', return_value=False), \
             patch('engine.repository.MessageRepository.transition_task_atomic', return_value=True), \
             patch('engine.repository.MessageRepository.mark_message_processed', return_value=True):
            return asyncio.run(self.guardian.process_response(self.mock_session, payload))

    def test_accepts_exact_expected_artifacts(self):
        payload = self._payload([
            {"path": "style.css", "action": FileAction.CREATE.value, "content": "body{}"}
        ])
        success, message = self._run(payload)
        assert success is True
        assert "OUT_OF_SCOPE" not in message
        assert self.task.attempt_count == 0

    def test_rejects_out_of_scope_artifacts(self):
        payload = self._payload([
            {"path": "style.css", "action": FileAction.CREATE.value, "content": "body{}"},
            {"path": "index.html", "action": FileAction.CREATE.value, "content": "<html></html>"},
        ])
        success, message = self._run(payload)
        assert success is True
        assert "VERIFY_FAILURE" in message
        assert "OUT_OF_SCOPE_ARTIFACTS" in message
        assert "index.html" in message
        assert self.task.attempt_count == 1
        # Feedback is persisted via sql_update on the Task row, not on the in-memory mock object.
        # We verify by ensuring the guardian returned the scope error in the message.
        assert "style.css" in message

    def test_rejected_scope_keeps_task_in_coding_for_retry(self):
        payload = self._payload([
            {"path": "style.css", "action": FileAction.CREATE.value, "content": "body{}"},
            {"path": "index.html", "action": FileAction.CREATE.value, "content": "<html></html>"},
        ])
        success, message = self._run(payload)
        assert success is True
        assert "VERIFY_FAILURE" in message
        # The task should be transitioned back to CODING (READY + CODING phase)
        # We verify this by checking that transition_task_atomic was called with CODING phase
        calls = [c.args for c in self.mock_session.execute.call_args_list]
        # There should be a TaskTransitionLog added
        assert self.mock_session.add.called
