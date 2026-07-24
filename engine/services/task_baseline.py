"""
Per-task baseline snapshots for scoped verification.

Problem
-------
The run-global baseline (``workspace/<run_id>/baseline_manifest.json``) is captured
before task-1 runs. When task-2 is verified, the workspace already contains task-1's
legitimate changes — so the global diff sees them as protected/out-of-scope drift.

Solution
--------
Take a fresh manifest snapshot **after** the previous task finished and **before**
the next CODER task spawns. Store it under::

    workspace/<run_id>/.task_baselines/<task_id>_rev<state_revision>.json

The ScopeVerifierAdapter prefers the per-task baseline if present, otherwise falls
back to the run-global baseline (backward compat / from-scratch safety).
"""
import json
import os
from datetime import datetime, timezone

from engine.services.baseline_manifest import build_manifest, save_manifest, load_manifest
from engine.services.ingest_context import get_ingest
from engine.settings import INGEST_EXCLUSIONS

import logging

logger = logging.getLogger(__name__)


def _task_baselines_dir(run_id: str) -> str:
    ing = get_ingest(run_id)
    if not ing:
        return ""
    ws = ing.get("workspace_root", "")
    if not ws:
        return ""
    # sibling of workspace/<run_id>/project -> workspace/<run_id>/.task_baselines
    return os.path.join(os.path.dirname(ws), ".task_baselines")


def task_baseline_path(run_id: str, task_id: str, state_revision: int) -> str:
    d = _task_baselines_dir(run_id)
    if not d:
        return ""
    return os.path.join(d, f"{task_id}_rev{state_revision}.json")


def save_task_baseline(run_id: str, task_id: str, state_revision: int) -> str:
    """Snapshot the current workspace project tree for this task.

    Returns the path written, or "" on failure / no ingest context.
    """
    ing = get_ingest(run_id)
    if not ing:
        return ""
    ws_root = ing.get("workspace_root")
    if not ws_root or not os.path.isdir(ws_root):
        return ""
    d = _task_baselines_dir(run_id)
    if not d:
        return ""
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{task_id}_rev{state_revision}.json")
    try:
        manifest = build_manifest(ws_root, exclusions=INGEST_EXCLUSIONS, run_id=run_id)
        manifest["task_id"] = task_id
        manifest["state_revision"] = state_revision
        manifest["baseline_kind"] = "per_task"
        save_manifest(manifest, path)
        logger.info("[TaskBaseline] Saved per-task baseline for %s rev %d -> %s", task_id, state_revision, path)
        return path
    except Exception:
        logger.exception("[TaskBaseline] Failed to save baseline for %s rev %d", task_id, state_revision)
        return ""


def load_task_baseline(run_id: str, task_id: str, state_revision: int):
    """Load a specific per-task baseline, or None if missing/invalid."""
    path = task_baseline_path(run_id, task_id, state_revision)
    if not path or not os.path.isfile(path):
        return None
    try:
        return load_manifest(path)
    except Exception:
        return None


def find_latest_task_baseline(run_id: str, task_id: str):
    """Find the most recent baseline for *task_id* (any revision).

    Used as a fallback when the exact (task_id, state_revision) baseline is missing
    but an earlier snapshot for the same task exists (e.g., retry with same rev).
    """
    d = _task_baselines_dir(run_id)
    if not d or not os.path.isdir(d):
        return None
    prefix = f"{task_id}_rev"
    candidates = []
    for fn in os.listdir(d):
        if fn.startswith(prefix) and fn.endswith(".json"):
            full = os.path.join(d, fn)
            try:
                rev_str = fn[len(prefix):-len(".json")]
                rev = int(rev_str)
                candidates.append((rev, full, os.path.getmtime(full)))
            except ValueError:
                continue
    if not candidates:
        return None
    # Prefer newest mtime; tie-break by higher revision.
    candidates.sort(key=lambda x: (x[2], x[0]), reverse=True)
    _, best_path, _ = candidates[0]
    try:
        return load_manifest(best_path)
    except Exception:
        return None


def resolve_baseline_for_task(run_id: str, task_id: str, state_revision: int):
    """Return the best available baseline manifest for verifying *task_id*.

    Precedence:
    1. exact (task_id, state_revision)
    2. latest baseline for same task_id
    3. None  -> caller should fall back to run-global baseline
    """
    m = load_task_baseline(run_id, task_id, state_revision)
    if m is not None:
        return m
    m = find_latest_task_baseline(run_id, task_id)
    if m is not None:
        logger.info("[TaskBaseline] Using fallback baseline for %s (exact rev %d not found)", task_id, state_revision)
    return m
