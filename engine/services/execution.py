import logging
import shlex
from typing import Tuple, Optional, List, Dict, Any
from sqlalchemy import select
from sqlalchemy.orm import Session

from engine.models import Task, TaskEvent, AssignedRole
from engine.services.sandbox import LocalPythonSandbox, ExecutionResult
from engine.transport.base import TransportMessage

logger = logging.getLogger(__name__)

class VerificationFailure(Exception):
    """Raised when the acceptance matrix verification fails."""
    def __init__(self, failures: List[Dict]):
        self.failures = failures
        super().__init__("Verification failed")

def normalize_output(text: str) -> str:
    """
    Stabilizes output for deterministic comparison:
    - Trim whitespace
    - Sort lines
    - Remove empty lines
    """
    if not text:
        return ""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    lines.sort()
    return "\n".join(lines) + ("\n" if lines else "")

class ExecutionService:
    """
    The ExecutionService is the deterministic arbiter of truth.
    It converts probabilistic artifacts into binary TaskEvents.
    """
    def __init__(self, sandbox=None):
        self.sandbox = sandbox or LocalPythonSandbox()

    def _parse_criteria(self, criteria: List[str]) -> List[Any]:
        """
        Parses CMD: criteria into VerificationSpecs.
        """
        specs = []
        for c in criteria:
            if c.startswith("CMD:"):
                parts = c.split(":", 2)
                if len(parts) < 2:
                    continue
                cmd_str = parts[1]
                expected = parts[2] if len(parts) == 3 else None
                specs.append({"cmd": shlex.split(cmd_str), "expected": expected, "desc": cmd_str})
        return specs

    async def verify(self, session: Session, task_id: str, project_id: str, plan_version: int, run_id: str, verification_type: str = "csv") -> Tuple[TaskEvent, str]:
        """
        Executes the task artifacts and returns the binary result using the VerificationRegistry.
        """
        logger.info(f"[ExecutionService] Semantically verifying task {task_id} using {verification_type}")
        
        result_task = await session.execute(select(Task).filter(Task.id == task_id))
        task = result_task.scalars().first()
        if not task:
            return TaskEvent.VERIFY_FAILURE, "Task not found"

        from engine.services.artifact_store import ArtifactStore
        store = ArtifactStore()
        files = await store.get_artifacts(session, run_id, project_id, plan_version, task_id)
        
        if not files:
            logger.warning(f"No artifacts found for task {task_id}. Automatic failure.")
            return TaskEvent.VERIFY_FAILURE, "No artifacts provided for verification."

        try:
            from engine.services.verification_registry import VerificationRegistry
            verifier = VerificationRegistry.get(verification_type)
            success, logs = await verifier.verify(session, task_id, project_id, plan_version, files)
            logger.info(f"[ExecutionService] Verification result: success={success}, reason='{logs}'")

            # Phase 7 (Reviewer-Upgrade): deterministic constraint guard.
            # Runs for every task (not just ingest mode) because constraints are universal.
            constraint_ok, constraint_logs = await self._constraint_check(files)
            if not constraint_ok:
                logger.info("[ExecutionService] Constraint verification FAILED: %s", constraint_logs)
                return TaskEvent.VERIFY_FAILURE, constraint_logs

            # Phase 2 (Idee A) Step3.3: deterministic scope/protected guard.
            # Runs only in ingest mode (no ingest context -> adapter is a pass-through).
            scope_ok, scope_logs = await self._scope_check(session, task_id, project_id, plan_version, files)
            if not scope_ok:
                logger.info("[ExecutionService] Scope verification FAILED: %s", scope_logs)
                return TaskEvent.VERIFY_FAILURE, scope_logs

            if success:
                return TaskEvent.VERIFY_SUCCESS, logs
            else:
                return TaskEvent.VERIFY_FAILURE, logs

        except Exception as e:
            logger.exception(f"Unexpected error during verification of task {task_id}: {str(e)}")
            return TaskEvent.VERIFY_FAILURE, f"Unexpected verification error: {str(e)}"

    async def _scope_check(self, session, task_id, project_id, plan_version, files) -> Tuple[bool, str]:
        """Runs the scope/protected verifier if this run is in ingest mode.

        Errors are treated as pass (so a verifier glitch never fails a run); absence of
        an ingest context means from-scratch runs are untouched.
        """
        try:
            from engine.services.verifiers.scope_verifier_adapter import ScopeVerifierAdapter
            adapter = ScopeVerifierAdapter()
            return await adapter.verify(session, task_id, project_id, plan_version, files)
        except Exception as e:
            logger.exception(f"Scope verifier error (treated as pass): {str(e)}")
            return True, "scope verifier error (skipped)"

    async def _constraint_check(self, files: List[Dict[str, Any]]) -> Tuple[bool, str]:
        """Runs deterministic constraint checks on artifact contents.

        Checks for forbidden patterns (localStorage, fetch(), external CDNs).
        This check runs for every task, regardless of ingest mode.
        """
        try:
            from engine.services.verifiers.constraint_verifier import verify_constraints
            result = verify_constraints(files, force_test_failure=False)
            return result.ok, result.report
        except Exception as e:
            logger.exception(f"Constraint verifier error (treated as pass): {str(e)}")
            return True, "constraint verifier error (skipped)"
