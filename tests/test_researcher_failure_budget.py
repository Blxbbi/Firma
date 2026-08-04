"""
Tests that TASK_FAILED in RESEARCHING consumes retry budget and terminates
after MAX_ITERATIONS instead of looping infinitely.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from engine.models import ExecutionPhase, TaskEvent, AssignedRole, WorkerResponse
from engine.services.guardian import GuardianPipeline
from engine.governance import GovernanceMatrix


@pytest.fixture
def guardian():
    artifact_store = MagicMock()
    return GuardianPipeline(artifact_store)


def _make_task(attempt_count=0, execution_phase=ExecutionPhase.RESEARCHING.value, assigned_role=AssignedRole.RESEARCHER.value):
    task = MagicMock()
    task.id = "task-research-1"
    task.plan_id = "plan-1"
    task.plan.project_id = "proj-1"
    task.execution_phase = execution_phase
    task.assigned_role = assigned_role
    task.state_revision = 1
    task.attempt_count = attempt_count
    task.retry_count = 0
    task.max_retries = 3
    task.expected_artifacts = []
    return task


def _make_response(event=TaskEvent.TASK_FAILED, sender_role=AssignedRole.RESEARCHER, artifacts=None):
    return WorkerResponse(
        message_id="msg-1",
        task_id="task-research-1",
        run_id="run-1",
        state_revision=1,
        event=event,
        sender_role=sender_role,
        artifacts=artifacts or [],
        timestamp="2026-07-27T00:00:00Z",
    )


def _run_async(coro):
    return asyncio.run(coro)


class TestResearcherFailureBudget:
    """Deterministic budget enforcement for TASK_FAILED in RESEARCHING."""

    def test_task_failed_in_researching_increments_attempt_count(self, guardian):
        """First TASK_FAILED in RESEARCHING increments attempt_count and retries."""
        session = AsyncMock()
        task = _make_task(attempt_count=0)
        response = _make_response()

        # Mock DB query returning the task
        result = MagicMock()
        result.scalars.return_value.first.return_value = task
        session.execute.return_value = result

        repo_mock = MagicMock()
        repo_mock.mark_message_processed = AsyncMock()
        repo_mock.transition_task_atomic = AsyncMock(return_value=True)
        repo_mock.save_submission_log = AsyncMock()

        with patch.dict("os.environ", {"FIRMA_MAX_ITERATIONS": "3"}):
            # Reload the class attribute after env change
            from engine.services import guardian as guardian_module
            original_max = guardian_module.GuardianPipeline.MAX_ITERATIONS
            guardian_module.GuardianPipeline.MAX_ITERATIONS = 3
            try:
                with patch("engine.repository.MessageRepository", return_value=repo_mock):
                    success, msg = _run_async(guardian.process_response(session, response.model_dump(), run_id="run-1"))
            finally:
                guardian_module.GuardianPipeline.MAX_ITERATIONS = original_max

        assert success is True
        assert task.attempt_count == 1
        # Should remain in RESEARCHING for retry
        assert task.execution_phase == ExecutionPhase.RESEARCHING.value

    def test_task_failed_exhausts_budget_after_max_iterations(self, guardian):
        """After MAX_ITERATIONS failures, task becomes FAILED_ITERATION_LIMIT."""
        session = AsyncMock()

        repo_mock = MagicMock()
        repo_mock.mark_message_processed = AsyncMock()
        repo_mock.transition_task_atomic = AsyncMock(return_value=True)
        repo_mock.save_submission_log = AsyncMock()

        with patch.dict("os.environ", {"FIRMA_MAX_ITERATIONS": "3"}):
            from engine.services import guardian as guardian_module
            original_max = guardian_module.GuardianPipeline.MAX_ITERATIONS
            guardian_module.GuardianPipeline.MAX_ITERATIONS = 3
            try:
                task = _make_task(attempt_count=2)  # 2 + 1 = 3 = MAX_ITERATIONS
                response = _make_response()

                result = MagicMock()
                result.scalars.return_value.first.return_value = task
                session.execute.return_value = result

                with patch("engine.repository.MessageRepository", return_value=repo_mock):
                    success, msg = _run_async(guardian.process_response(session, response.model_dump(), run_id="run-1"))
            finally:
                guardian_module.GuardianPipeline.MAX_ITERATIONS = original_max

        assert success is True
        assert task.attempt_count == 3
        # Verify transition_task_atomic was called with FAILED_ITERATION_LIMIT
        repo_mock.transition_task_atomic.assert_called()
        call_kwargs = repo_mock.transition_task_atomic.call_args[1]
        assert call_kwargs["new_phase"] == ExecutionPhase.FAILED_ITERATION_LIMIT.value

    def test_task_failed_in_planning_also_consumes_budget(self, guardian):
        """TASK_FAILED in PLANNING also increments attempt_count."""
        session = AsyncMock()
        task = _make_task(
            attempt_count=0,
            execution_phase=ExecutionPhase.PLANNING.value,
            assigned_role=AssignedRole.PLANNER.value,
        )
        response = _make_response(sender_role=AssignedRole.PLANNER)

        result = MagicMock()
        result.scalars.return_value.first.return_value = task
        session.execute.return_value = result

        repo_mock = MagicMock()
        repo_mock.mark_message_processed = AsyncMock()
        repo_mock.transition_task_atomic = AsyncMock(return_value=True)
        repo_mock.save_submission_log = AsyncMock()

        with patch.dict("os.environ", {"FIRMA_MAX_ITERATIONS": "3"}):
            from engine.services import guardian as guardian_module
            original_max = guardian_module.GuardianPipeline.MAX_ITERATIONS
            guardian_module.GuardianPipeline.MAX_ITERATIONS = 3
            try:
                with patch("engine.repository.MessageRepository", return_value=repo_mock):
                    success, msg = _run_async(guardian.process_response(session, response.model_dump(), run_id="run-1"))
            finally:
                guardian_module.GuardianPipeline.MAX_ITERATIONS = original_max

        assert success is True
        assert task.attempt_count == 1
        # Should remain in PLANNING for retry (not immediately FAILED)
        assert task.execution_phase == ExecutionPhase.PLANNING.value

    def test_governance_matrix_allows_retry_on_task_failed_in_researching(self):
        """Governance matrix should map TASK_FAILED in RESEARCHING back to RESEARCHING."""
        result = GovernanceMatrix.transition(ExecutionPhase.RESEARCHING, TaskEvent.TASK_FAILED)
        assert result.next_phase == ExecutionPhase.RESEARCHING
        assert result.next_role == AssignedRole.RESEARCHER

    def test_governance_matrix_allows_retry_on_task_failed_in_planning(self):
        """Governance matrix should map TASK_FAILED in PLANNING back to PLANNING."""
        result = GovernanceMatrix.transition(ExecutionPhase.PLANNING, TaskEvent.TASK_FAILED)
        assert result.next_phase == ExecutionPhase.PLANNING
        assert result.next_role == AssignedRole.PLANNER

    def test_governance_matrix_allows_retry_on_task_failed_in_coding(self):
        """Governance matrix should map TASK_FAILED in CODING back to CODING."""
        result = GovernanceMatrix.transition(ExecutionPhase.CODING, TaskEvent.TASK_FAILED)
        assert result.next_phase == ExecutionPhase.CODING
        assert result.next_role == AssignedRole.CODER
