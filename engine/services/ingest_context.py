"""
Phase 2 (Idee A) - Step3.3: in-memory ingest context for a run.

Maps:
  run_id -> {workspace_root, baseline_path}
  (run_id, task_id) -> {scope_files, protected_files}

In-memory (single process). Sufficient for the prototype and the E2E (one process).
The persisted source of truth remains the baseline manifest on disk + the workspace tree.
"""
import threading
from typing import Dict, List, Optional

_lock = threading.Lock()
_INGEST: Dict[str, dict] = {}
_TASK_SCOPE: Dict[tuple, dict] = {}


def register_ingest(run_id: str, workspace_root: str, baseline_path: str) -> None:
    with _lock:
        _INGEST[run_id] = {"workspace_root": workspace_root, "baseline_path": baseline_path}


def get_ingest(run_id: str) -> Optional[dict]:
    with _lock:
        return _INGEST.get(run_id)


def clear_ingest(run_id: str) -> None:
    with _lock:
        _INGEST.pop(run_id, None)
        for k in list(_TASK_SCOPE.keys()):
            if k[0] == run_id:
                _TASK_SCOPE.pop(k, None)


def set_task_scope(run_id: str, task_id: str, scope_files: List[str], protected_files: List[str]) -> None:
    with _lock:
        _TASK_SCOPE[(run_id, task_id)] = {
            "scope_files": list(scope_files),
            "protected_files": list(protected_files),
        }


def get_task_scope(run_id: str, task_id: str) -> Optional[dict]:
    with _lock:
        return _TASK_SCOPE.get((run_id, task_id))


def get_all_task_scopes(run_id: str) -> Dict[str, dict]:
    """Return {task_id: {scope_files, protected_files}} for all tasks of a run."""
    with _lock:
        return {
            tid: {"scope_files": v["scope_files"], "protected_files": v["protected_files"]}
            for (r, tid), v in _TASK_SCOPE.items()
            if r == run_id
        }
