"""
Integration test for kernel-side plan validation in GuardianPipeline.process_response.
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
from engine.models import Task, Plan, ExecutionPhase, AssignedRole, TaskEvent
import uuid
from datetime import datetime, timezone


class _FakePlan:
    project_id = "proj-123"
    version = 1


class _FakeTask:
    id = "planner-1"
    plan_id = "plan-1"
    state = "CLAIMED"
    updated_at = datetime.now(timezone.utc)
    plan = _FakePlan()
    execution_phase = ExecutionPhase.PLANNING.value
    assigned_role = AssignedRole.PLANNER.value
    state_revision = 1
    attempt_count = 0
    last_review_feedback = None


class TestGuardianPlanRejection:
    def setup_method(self):
        self.mock_session = MagicMock(spec=Session)
        self.mock_artifact_store = MagicMock(spec=ArtifactStore)
        self.guardian = GuardianPipeline(self.mock_artifact_store)

        task = _FakeTask()
        self.task = task

        # Make session.execute async-compatible
        async def fake_execute(stmt):
            return MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=task))))
        self.mock_session.execute = AsyncMock(side_effect=fake_execute)
        self.mock_session.flush = AsyncMock(return_value=None)
        self.mock_session.refresh = AsyncMock(return_value=None)
        self.mock_session.add = MagicMock()

    def _payload(self, plan_tasks):
        return {
            "protocol_version": "1.0",
            "message_id": str(uuid.uuid4()),
            "task_id": "planner-1",
            "run_id": "run-1",
            "state_revision": 1,
            "event": TaskEvent.PLAN_SUBMITTED.value,
            "sender_role": AssignedRole.PLANNER.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "logs": "stub plan",
            "plan_draft": {
                "plan_name": "Test Plan",
                "tasks": plan_tasks,
            },
        }

    def _run(self, payload):
        with patch('engine.repository.MessageRepository.is_message_processed', return_value=False), \
             patch('engine.repository.MessageRepository.transition_task_atomic', return_value=True), \
             patch('engine.repository.MessageRepository.mark_message_processed', return_value=True):
            return asyncio.run(self.guardian.process_response(self.mock_session, payload))

    def _task_update_calls(self):
        """Return Update statements that target the tasks table."""
        calls = []
        for c in self.mock_session.execute.call_args_list:
            arg = c.args[0]
            if hasattr(arg, '__class__') and 'Update' in arg.__class__.__name__:
                if 'tasks' in str(arg).lower():
                    calls.append(arg)
        return calls

    def test_valid_plan_is_accepted(self):
        payload = self._payload([
            {"id": "task-1", "description": "do it", "role": "CODER", "expected_artifacts": [{"path": "a.py", "type": "CREATE"}], "acceptance_criteria": []},
        ])
        success, message = self._run(payload)
        assert success is True
        # Valid plan updates projects.active_plan_id, not tasks.last_review_feedback
        task_updates = self._task_update_calls()
        assert len(task_updates) == 0
        assert self.task.attempt_count == 0

    def test_plan_with_empty_tasks_is_rejected(self):
        original_max = GuardianPipeline.MAX_ITERATIONS
        try:
            GuardianPipeline.MAX_ITERATIONS = 2
            payload = self._payload([])
            success, message = self._run(payload)
            assert success is True
            # Rejection sets last_review_feedback on the Task
            task_updates = self._task_update_calls()
            assert len(task_updates) == 1
            assert "last_review_feedback" in str(task_updates[0])
            # attempt_count must be incremented on rejection
            assert self.task.attempt_count == 1
        finally:
            GuardianPipeline.MAX_ITERATIONS = original_max

    def test_plan_with_coder_task_without_artifacts_is_rejected(self):
        original_max = GuardianPipeline.MAX_ITERATIONS
        try:
            GuardianPipeline.MAX_ITERATIONS = 2
            payload = self._payload([
                {"id": "task-1", "description": "do it", "role": "CODER", "expected_artifacts": [], "acceptance_criteria": []},
            ])
            success, message = self._run(payload)
            assert success is True
            task_updates = self._task_update_calls()
            assert len(task_updates) == 1
            assert "last_review_feedback" in str(task_updates[0])
            assert self.task.attempt_count == 1
        finally:
            GuardianPipeline.MAX_ITERATIONS = original_max

    def test_plan_with_too_many_tasks_is_rejected(self):
        original_max = GuardianPipeline.MAX_ITERATIONS
        try:
            GuardianPipeline.MAX_ITERATIONS = 2
            payload = self._payload([
                {"id": f"t{i}", "description": "do it", "role": "CODER", "expected_artifacts": [{"path": "x.py", "type": "CREATE"}], "acceptance_criteria": []}
                for i in range(6)
            ])
            success, message = self._run(payload)
            assert success is True
            task_updates = self._task_update_calls()
            assert len(task_updates) == 1
            assert "last_review_feedback" in str(task_updates[0])
            assert self.task.attempt_count == 1
        finally:
            GuardianPipeline.MAX_ITERATIONS = original_max

    def test_plan_reject_increments_attempt_count(self):
        """Explicit test: PLAN_REJECTED consumes retry budget."""
        original_max = GuardianPipeline.MAX_ITERATIONS
        try:
            GuardianPipeline.MAX_ITERATIONS = 2
            self.task.attempt_count = 0
            payload = self._payload([])
            success, message = self._run(payload)
            assert success is True
            assert self.task.attempt_count == 1
        finally:
            GuardianPipeline.MAX_ITERATIONS = original_max

    def test_planner_stops_after_max_iterations_on_rejects(self):
        """Planner task fails after MAX_ITERATIONS rejections."""
        original_max = GuardianPipeline.MAX_ITERATIONS
        try:
            GuardianPipeline.MAX_ITERATIONS = 2
            self.task.attempt_count = 1  # already failed once
            
            payload = self._payload([])
            success, message = self._run(payload)
            assert success is True
            assert self.task.attempt_count == 2
            # After hitting max iterations, the task should transition to FAILED
            # The mock transition_task_atomic is called with new_state="FAILED"
            # We verify this by checking that last_review_feedback is NOT set (no retry)
            task_updates = self._task_update_calls()
            # When limit is reached, we don't update last_review_feedback (no retry)
            assert len(task_updates) == 0
        finally:
            GuardianPipeline.MAX_ITERATIONS = original_max
