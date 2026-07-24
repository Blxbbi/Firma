"""
Per-task baseline snapshot tests (A: fix false-positive scope verification).
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.services.ingest_context import register_ingest, clear_ingest, set_task_scope
from engine.services.task_baseline import (
    task_baseline_path,
    save_task_baseline,
    load_task_baseline,
    find_latest_task_baseline,
    resolve_baseline_for_task,
)
from engine.services.baseline_manifest import build_manifest, save_manifest


def _setup_ingest(tmp, run_id):
    ws = os.path.join(tmp, run_id, "project")
    bl = os.path.join(tmp, run_id, "baseline_manifest.json")
    os.makedirs(ws, exist_ok=True)
    register_ingest(run_id, ws, bl)
    return ws, bl


def test_save_and_load_task_baseline():
    import tempfile, shutil
    tmp = tempfile.mkdtemp()
    try:
        run_id = "run-1"
        ws, bl = _setup_ingest(tmp, run_id)
        # seed workspace
        for name in ("index.html", "style.css", "app.js"):
            with open(os.path.join(ws, name), "w", encoding="utf-8") as f:
                f.write(name)
        # exact rev
        p = save_task_baseline(run_id, "task-1", 1)
        assert p and os.path.isfile(p), p
        m = load_task_baseline(run_id, "task-1", 1)
        assert m is not None
        assert m.get("task_id") == "task-1"
        assert m.get("state_revision") == 1
        assert m.get("baseline_kind") == "per_task"
        # wrong rev -> None
        assert load_task_baseline(run_id, "task-1", 2) is None
    finally:
        clear_ingest(run_id)
        shutil.rmtree(tmp)


def test_find_latest_task_baseline_fallback():
    import tempfile, shutil
    tmp = tempfile.mkdtemp()
    try:
        run_id = "run-2"
        ws, bl = _setup_ingest(tmp, run_id)
        for name in ("index.html",):
            with open(os.path.join(ws, name), "w", encoding="utf-8") as f:
                f.write(name)
        save_task_baseline(run_id, "task-1", 1)
        save_task_baseline(run_id, "task-1", 2)
        # exact rev missing, but latest for same task exists
        m = find_latest_task_baseline(run_id, "task-1")
        assert m is not None
        assert m.get("state_revision") == 2
        # different task -> None
        assert find_latest_task_baseline(run_id, "task-99") is None
    finally:
        clear_ingest(run_id)
        shutil.rmtree(tmp)


def test_resolve_baseline_prefers_exact_then_fallback():
    import tempfile, shutil
    tmp = tempfile.mkdtemp()
    try:
        run_id = "run-3"
        ws, bl = _setup_ingest(tmp, run_id)
        for name in ("index.html",):
            with open(os.path.join(ws, name), "w", encoding="utf-8") as f:
                f.write(name)
        save_task_baseline(run_id, "task-1", 1)
        # exact match
        m = resolve_baseline_for_task(run_id, "task-1", 1)
        assert m is not None and m.get("state_revision") == 1
        # fallback to latest when exact missing
        m2 = resolve_baseline_for_task(run_id, "task-1", 99)
        assert m2 is not None and m2.get("state_revision") == 1
        # no baseline at all -> None
        assert resolve_baseline_for_task(run_id, "task-99", 1) is None
    finally:
        clear_ingest(run_id)
        shutil.rmtree(tmp)


def test_no_ingest_context_returns_empty():
    clear_ingest("no-such-run")
    assert save_task_baseline("no-such-run", "task-1", 1) == ""
    assert load_task_baseline("no-such-run", "task-1", 1) is None
    assert find_latest_task_baseline("no-such-run", "task-1") is None
    assert resolve_baseline_for_task("no-such-run", "task-1", 1) is None


if __name__ == "__main__":
    failures = []
    for name, fn in [
        ("test_save_and_load_task_baseline", test_save_and_load_task_baseline),
        ("test_find_latest_task_baseline_fallback", test_find_latest_task_baseline_fallback),
        ("test_resolve_baseline_prefers_exact_then_fallback", test_resolve_baseline_prefers_exact_then_fallback),
        ("test_no_ingest_context_returns_empty", test_no_ingest_context_returns_empty),
    ]:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {name}: {e}")
            failures.append(name)
    if failures:
        print(f"{len(failures)} FAILURES: {failures}")
        raise SystemExit(1)
    print("OK")
