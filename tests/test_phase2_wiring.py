"""
Phase 2 (Idee A) - Step3.3: light integration wiring tests.

Run via: ./tools/safe_test.sh tests/test_phase2_wiring.py

These are "integration light" (no LLM): they prove the wiring pieces connect
(ingest -> registry, and verify -> scope_verifier with the task's scope fields),
using direct calls / mocks. The full E2E is a separate step.
"""
import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.services.ingest import setup_ingest_run
from engine.services.ingest_context import get_ingest, set_task_scope, clear_ingest
from engine.services.verifiers.scope_verifier_adapter import ScopeVerifierAdapter
from engine.services import verifiers as verifiers_pkg
from engine.models import Task


def _seed(root, layout):
    for rel, content in layout.items():
        full = os.path.join(root, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)


def test_ingest_wiring_writes_baseline_when_project_dir_set():
    src = tempfile.mkdtemp()
    ws = tempfile.mkdtemp()
    try:
        _seed(src, {"index.html": "a", "style.css": "s", "app.js": "c"})
        run_id = "run-wiring-1"
        manifest = setup_ingest_run(run_id, src=src, workspace_dir=ws)
        assert manifest is not None, "setup_ingest_run returned None"
        baseline = os.path.join(ws, run_id, "baseline_manifest.json")
        assert os.path.exists(baseline), "baseline_manifest.json not written"
        ing = get_ingest(run_id)
        assert ing is not None
        assert ing["workspace_root"] == os.path.join(ws, run_id, "project")
        assert ing["baseline_path"] == baseline
        clear_ingest(run_id)
    finally:
        shutil.rmtree(src)
        shutil.rmtree(ws)


def test_verify_calls_scope_verifier_with_task_definition_fields():
    run_id = "r-wiring-2"
    task_id = "task-wiring-2"
    register = get_ingest  # alias for clarity
    from engine.services.ingest_context import register_ingest
    register_ingest(run_id, "/tmp/ws/project", "/tmp/ws/baseline.json")
    set_task_scope(run_id, task_id, ["style.css"], ["app.js", "index.html"])

    captured = {}

    class FakeResult:
        ok = False
        code = "PROTECTED_VIOLATION"
        changed = []
        deleted = []
        new = []
        report = "x"

        def to_dict(self):
            return {"ok": self.ok, "code": self.code}

    def fake_verify(workspace_root, baseline_manifest_path, scope_files=None,
                    protected_files=None, exclusions=None, allow_new_files=None):
        captured["workspace_root"] = workspace_root
        captured["baseline_manifest_path"] = baseline_manifest_path
        captured["scope_files"] = scope_files
        captured["protected_files"] = protected_files
        return FakeResult()

    sv_mod = verifiers_pkg.scope_verifier_adapter
    orig = sv_mod.verify_scope
    sv_mod.verify_scope = fake_verify
    try:
        # minimal fake session that returns a Task with run_id
        class _FakeResult:
            def scalars(self):
                return self

            def first(self):
                return self._task

        class _FakeSession:
            def __init__(self, task):
                self._r = _FakeResult()
                self._r._task = task

            async def execute(self, *a, **k):
                return self._r

        task = Task(id=task_id, run_id=run_id)
        sess = _FakeSession(task)
        adapter = ScopeVerifierAdapter()
        ok, logs = asyncio.run(adapter.verify(sess, task_id, "proj", 1, []))
        assert ok is False, logs
        assert captured["workspace_root"] == "/tmp/ws/project"
        assert captured["scope_files"] == ["style.css"], captured
        assert captured["protected_files"] == ["app.js", "index.html"], captured
    finally:
        sv_mod.verify_scope = orig
        clear_ingest(run_id)


if __name__ == "__main__":
    failures = []
    for name, fn in [
        ("test_ingest_wiring_writes_baseline_when_project_dir_set", test_ingest_wiring_writes_baseline_when_project_dir_set),
        ("test_verify_calls_scope_verifier_with_task_definition_fields", test_verify_calls_scope_verifier_with_task_definition_fields),
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
