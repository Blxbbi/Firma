"""
Regression: per-task baseline prevents false-positive scope verification.

Scenario (exact false positive from run 88d6067d):
- Baseline run-global: index.html=A, style.css=B, app.js=C
- task-1 scope=index.html changes index.html -> A'
- task-2 scope=style.css changes ONLY style.css -> B'
- Old verifier (run-global baseline): sees index.html drift -> false positive
- New verifier (per-task baseline): sees only style.css drift -> pass
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.services.ingest_context import register_ingest, clear_ingest, set_task_scope
from engine.services.baseline_manifest import build_manifest, save_manifest
from engine.services.verifiers.scope_verifier_adapter import ScopeVerifierAdapter
from engine.services.verification_registry import BaseVerifier
from engine.models import Task


def _fake_session():
    class FakeResult:
        def scalar_one_or_none(self):
            return None
    class FakeExec:
        def execute(self, stmt):
            return FakeResult()
    return FakeExec()


class _FakeAdapter(ScopeVerifierAdapter):
    """Subclass that bypasses DB session by injecting task/run context directly."""
    def __init__(self, run_id, task_id, state_revision):
        self._run_id = run_id
        self._task_id = task_id
        self._state_revision = state_revision

    async def verify(self, session, task_id, project_id, plan_version, artifacts):  # noqa: ARG002
        from engine.services.ingest_context import get_ingest, get_task_scope
        from engine.services.task_baseline import resolve_baseline_for_task
        from engine.services.verifiers.scope_verifier import verify_scope
        import tempfile, os, json

        run_id = self._run_id
        task_id = self._task_id
        ing = get_ingest(run_id)
        if not ing:
            return True, "No ingest context for run; scope verifier skipped."
        scope = get_task_scope(run_id, task_id)
        if not scope:
            return True, "No scope defined for task; scope verifier skipped."

        baseline_path = ing["baseline_path"]
        per_task = resolve_baseline_for_task(run_id, task_id, self._state_revision)
        if per_task:
            tmp = None
            try:
                fd, tmp = tempfile.mkstemp(suffix=".json", prefix="scope_baseline_")
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(per_task, f, sort_keys=True, indent=2)
                baseline_path = tmp
            except Exception:
                if tmp and os.path.isfile(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                baseline_path = ing["baseline_path"]

        result = verify_scope(
            workspace_root=ing["workspace_root"],
            baseline_manifest_path=baseline_path,
            scope_files=scope["scope_files"],
            protected_files=scope["protected_files"],
        )
        if result.ok:
            return True, "scope ok"
        return False, f"SCOPE_VERIFY_{result.code}: {result.report}"


def test_false_positive_with_run_global_baseline():
    """Without per-task baseline, task-2 sees task-1's index.html change as violation."""
    import tempfile
    tmp = tempfile.mkdtemp()
    try:
        run_id = "run-fp"
        ws = os.path.join(tmp, run_id, "project")
        bl = os.path.join(tmp, run_id, "baseline_manifest.json")
        os.makedirs(ws, exist_ok=True)
        register_ingest(run_id, ws, bl)

        # seed baseline
        with open(os.path.join(ws, "index.html"), "w", encoding="utf-8") as f:
            f.write("INDEX_A")
        with open(os.path.join(ws, "style.css"), "w", encoding="utf-8") as f:
            f.write("STYLE_B")
        with open(os.path.join(ws, "app.js"), "w", encoding="utf-8") as f:
            f.write("APP_C")
        m = build_manifest(ws, run_id=run_id)
        save_manifest(m, bl)

        # task-1 changes index.html (its scope)
        with open(os.path.join(ws, "index.html"), "w", encoding="utf-8") as f:
            f.write("INDEX_A_PRIME")
        set_task_scope(run_id, "task-1", ["index.html"], ["style.css", "app.js"])

        # task-2 changes ONLY style.css (its scope)
        with open(os.path.join(ws, "style.css"), "w", encoding="utf-8") as f:
            f.write("STYLE_B_PRIME")
        set_task_scope(run_id, "task-2", ["style.css"], ["index.html", "app.js"])

        # Old path: no per-task baseline -> false positive
        adapter_old = _FakeAdapter(run_id, "task-2", 1)
        ok, msg = asyncio.get_event_loop().run_until_complete(
            adapter_old.verify(_fake_session(), "task-2", "proj", 1, [])
        )
        assert ok is False, f"Expected false positive with run-global baseline, got ok={ok} msg={msg}"
        assert "index.html" in msg, msg
    finally:
        clear_ingest(run_id)
        shutil.rmtree(tmp)


def test_per_task_baseline_avoids_false_positive():
    """With per-task baseline after task-1, task-2 verify passes."""
    import tempfile
    tmp = tempfile.mkdtemp()
    try:
        run_id = "run-ok"
        ws = os.path.join(tmp, run_id, "project")
        bl = os.path.join(tmp, run_id, "baseline_manifest.json")
        os.makedirs(ws, exist_ok=True)
        register_ingest(run_id, ws, bl)

        # seed baseline
        with open(os.path.join(ws, "index.html"), "w", encoding="utf-8") as f:
            f.write("INDEX_A")
        with open(os.path.join(ws, "style.css"), "w", encoding="utf-8") as f:
            f.write("STYLE_B")
        with open(os.path.join(ws, "app.js"), "w", encoding="utf-8") as f:
            f.write("APP_C")
        m = build_manifest(ws, run_id=run_id)
        save_manifest(m, bl)

        # task-1 changes index.html (its scope)
        with open(os.path.join(ws, "index.html"), "w", encoding="utf-8") as f:
            f.write("INDEX_A_PRIME")
        set_task_scope(run_id, "task-1", ["index.html"], ["style.css", "app.js"])
        # save per-task baseline for task-2 AFTER task-1 finished (as scheduler would do)
        from engine.services.task_baseline import save_task_baseline
        save_task_baseline(run_id, "task-2", 1)

        # task-2 changes ONLY style.css (its scope)
        with open(os.path.join(ws, "style.css"), "w", encoding="utf-8") as f:
            f.write("STYLE_B_PRIME")
        set_task_scope(run_id, "task-2", ["style.css"], ["index.html", "app.js"])

        # New path: per-task baseline -> pass
        adapter_new = _FakeAdapter(run_id, "task-2", 1)
        ok, msg = asyncio.get_event_loop().run_until_complete(
            adapter_new.verify(_fake_session(), "task-2", "proj", 1, [])
        )
        assert ok is True, f"Expected pass with per-task baseline, got ok={ok} msg={msg}"
        assert msg == "scope ok", msg
    finally:
        clear_ingest(run_id)
        shutil.rmtree(tmp)


def test_retry_baseline_uses_correct_revision():
    """When retrying same task with new revision, verifier picks the right baseline."""
    import tempfile
    tmp = tempfile.mkdtemp()
    try:
        run_id = "run-retry"
        ws = os.path.join(tmp, run_id, "project")
        bl = os.path.join(tmp, run_id, "baseline_manifest.json")
        os.makedirs(ws, exist_ok=True)
        register_ingest(run_id, ws, bl)

        with open(os.path.join(ws, "index.html"), "w", encoding="utf-8") as f:
            f.write("A")
        with open(os.path.join(ws, "style.css"), "w", encoding="utf-8") as f:
            f.write("B")
        m = build_manifest(ws, run_id=run_id)
        save_manifest(m, bl)

        set_task_scope(run_id, "task-1", ["style.css"], ["index.html"])
        from engine.services.task_baseline import save_task_baseline
        save_task_baseline(run_id, "task-1", 1)
        # mutate to rev2 baseline
        with open(os.path.join(ws, "style.css"), "w", encoding="utf-8") as f:
            f.write("B_V2")
        save_task_baseline(run_id, "task-1", 2)

        # rev1 should see style.css change from first baseline
        adapter_r1 = _FakeAdapter(run_id, "task-1", 1)
        ok1, msg1 = asyncio.get_event_loop().run_until_complete(
            adapter_r1.verify(_fake_session(), "task-1", "proj", 1, [])
        )
        assert ok1 is True, msg1

        # rev2 should see no change from second baseline
        adapter_r2 = _FakeAdapter(run_id, "task-1", 2)
        ok2, msg2 = asyncio.get_event_loop().run_until_complete(
            adapter_r2.verify(_fake_session(), "task-1", "proj", 1, [])
        )
        assert ok2 is True, msg2
    finally:
        clear_ingest(run_id)
        shutil.rmtree(tmp)


if __name__ == "__main__":
    failures = []
    for name, fn in [
        ("test_false_positive_with_run_global_baseline", test_false_positive_with_run_global_baseline),
        ("test_per_task_baseline_avoids_false_positive", test_per_task_baseline_avoids_false_positive),
        ("test_retry_baseline_uses_correct_revision", test_retry_baseline_uses_correct_revision),
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
