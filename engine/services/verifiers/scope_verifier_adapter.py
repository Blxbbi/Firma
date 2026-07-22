"""
Phase 2 (Idee A) - Step3.3: adapter that runs the scope/protected verifier as a BaseVerifier.

Reads the live workspace tree (the source of truth, materialized by the kernel from the
CODER's artifacts[]) + the baseline manifest captured at ingest, and the per-task
scope/protected (registered by the Guardian at PLAN_SUBMITTED). Calls ``verify_scope``.

If there is no ingest context for the run, or no scope defined for the task, it is a
no-op (pass) — from-scratch runs are completely unaffected.
"""
import logging
from typing import Tuple, List, Dict, Any

from sqlalchemy import select

from engine.services.verification_registry import BaseVerifier
from engine.services.verifiers.scope_verifier import verify_scope
from engine.services.ingest_context import get_ingest, get_task_scope
from engine.models import Task, TaskEvent

logger = logging.getLogger(__name__)


class ScopeVerifierAdapter(BaseVerifier):
    async def verify(
        self,
        session,
        task_id: str,
        project_id: str,
        plan_version: int,
        artifacts: List[Dict[str, Any]],
    ) -> Tuple[bool, str]:
        # Resolve run_id from the Task row (BaseVerifier signature has no run_id).
        task = (await session.execute(select(Task).filter(Task.id == task_id))).scalars().first()
        run_id = task.run_id if task else None

        ing = get_ingest(run_id)
        if not ing:
            return True, "No ingest context for run; scope verifier skipped."

        scope = get_task_scope(run_id, task_id)
        if not scope:
            return True, "No scope defined for task; scope verifier skipped."

        result = verify_scope(
            workspace_root=ing["workspace_root"],
            baseline_manifest_path=ing["baseline_path"],
            scope_files=scope["scope_files"],
            protected_files=scope["protected_files"],
        )
        if result.ok:
            return True, "scope ok"
        return False, f"SCOPE_VERIFY_{result.code}: {result.report}"
