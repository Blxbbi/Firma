"""
Phase 2 (Idee A) — End-to-End E2E: incremental edit with scope/protected guard.

Run via: ./tools/safe_test.sh tests/e2e_phase2_incremental.py

Design (deterministic, no LLM — Variante A, InternalTransport + StubWorker):
  We drive the REAL engine pipeline end-to-end:
    setup_ingest_run  -> workspace/<run_id>/project + baseline_manifest.json + registry
    Orchestrator/Scheduler -> dispatch PLANNER/CODER tasks
    StubWorker -> PLAN_SUBMITTED (expected_artifacts=["style.css"]) + CODE_SUBMITTED
    Guardian PLAN_SUBMITTED -> apply_ingest_scope -> set_task_scope (kernel-side policy)
    StubWorker materializes CODER artifacts into the WORKSPACE (truth) via the shared
        workspace_materializer service (exactly what the PiMesh Receiver does)
    Orchestrator verification phase -> ExecutionService.verify -> ScopeVerifierAdapter
        -> verify_scope(workspace, baseline, scope, protected)
    RunArchiver -> archive/runs/<run_id>/manifest.json with baseline pointer + scope_summary

Scenarios:
  POS  : CODER edits only style.css  -> Run COMPLETED, diff changed==["style.css"]
  NEG  : CODER also edits index.html -> Run FAILED, scope verifier flags PROTECTED/SCOPE violation
  LOCK : CODER also edits package-lock.json -> Run FAILED, lockfile drift detected
"""
import asyncio
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from engine.db import DatabaseManager
from engine.controller import RunController
from engine.scheduler import Scheduler
from engine.transport.internal_transport import InternalTransport
from engine.services.execution import ExecutionService
from engine.services.sandbox import LocalPythonSandbox
from engine.services.verification_registry import VerificationRegistry
from engine.services.verifiers.web_verifier import WebStructuralVerifier
from engine.services.baseline_manifest import build_manifest, load_manifest, diff_manifests
from engine.services.verifiers.scope_verifier import verify_scope
from engine.services.ingest import setup_ingest_run
from engine.services.ingest_context import get_ingest
from engine.services.workspace_materializer import materialize_to_workspace
from engine.services.run_archive import RunArchiver
from engine.models import Base

STYLE_RED = "button { background: red; }"
STYLE_BLUE = "button { background: blue; }"
INDEX_HTML = "<html><body><button id='b'>Click</button></body></html>"
APP_JS = "console.log('app');"
LOCK_JSON = '{"lockfileVersion": 3}'


async def _build_engine(tmp: Path):
    db_path = tmp / "e2e.db"
    if db_path.exists():
        db_path.unlink()
    db_manager = DatabaseManager(f"sqlite+aiosqlite:///{db_path}")
    async with db_manager.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    def scheduler_factory(db, messenger_callback):
        return Scheduler(db, messenger_callback=messenger_callback)

    transport = InternalTransport()

    def transport_factory():
        return transport

    execution_service = ExecutionService(db_manager)
    sandbox = LocalPythonSandbox()
    controller = RunController(
        db_manager, scheduler_factory, transport_factory, execution_service, sandbox
    )
    return controller, transport


async def _stub_worker(run_id, transport, negative, with_lockfile):
    """Deterministic worker: PLANNER -> plan (scope=style.css), CODER -> edits, REVIEWER -> approve."""
    while True:
        msg = await transport.get_dispatch()
        if not msg:
            await asyncio.sleep(0.02)
            continue
        if msg.get("event") != "TASK_ASSIGNMENT":
            continue
        role = msg.get("role")
        task_id = msg.get("task_id")
        rev = msg.get("state_revision")

        if role == "RESEARCHER":
            # Phase 3 (Idee B): researcher writes a read-only briefing under research/,
            # then completes. The Guardian enforces it touched no project file.
            ing = get_ingest(run_id)
            ws_root = ing["workspace_root"]
            research_dir = os.path.join(os.path.dirname(ws_root), "research")
            os.makedirs(research_dir, exist_ok=True)
            brief = "# Research Brief\n\nGrounding notes for the planner."
            with open(os.path.join(research_dir, "brief.md"), "w", encoding="utf-8") as f:
                f.write(brief)
            await transport.publish_response("RESEARCHER", {
                "protocol_version": "1.0",
                "message_id": f"research-{task_id}",
                "task_id": task_id,
                "run_id": run_id,
                "state_revision": rev,
                "event": "RESEARCH_COMPLETE",
                "sender_role": "RESEARCHER",
                "timestamp": datetime.now(timezone.utc),
                "logs": "stub research",
                "artifacts": [{"path": "research/brief.md", "action": "CREATE", "content": brief}],
            })

        elif role == "PLANNER":
            payload = {
                "protocol_version": "1.0",
                "message_id": f"plan-{run_id}",
                "task_id": task_id,
                "run_id": run_id,
                "state_revision": rev,
                "event": "PLAN_SUBMITTED",
                "sender_role": "PLANNER",
                "timestamp": datetime.now(timezone.utc),
                "logs": "stub plan",
                "plan_draft": {
                    "plan_name": "Incremental CSS Edit",
                    "tasks": [{
                        "id": "task-coder-1",
                        "description": "Change button color in style.css only",
                        "expected_artifacts": [{"path": "style.css", "type": "UPDATE"}],
                        "acceptance_criteria": ["EXISTS:style.css"],
                    }],
                },
            }
            await transport.publish_response("PLANNER", payload)

        elif role == "CODER":
            artifacts = [{"path": "style.css", "action": "UPDATE", "content": STYLE_BLUE}]
            if negative:
                artifacts.append(
                    {"path": "index.html", "action": "UPDATE",
                     "content": INDEX_HTML + "<!-- DRIFT -->"})
            if with_lockfile:
                artifacts.append(
                    {"path": "package-lock.json", "action": "UPDATE",
                     "content": '{"lockfileVersion": 3, "changed": true}'})
            payload = {
                "protocol_version": "1.0",
                "message_id": f"code-{task_id}-{rev}",
                "task_id": task_id,
                "run_id": run_id,
                "state_revision": rev,
                "event": "CODE_SUBMITTED",
                "sender_role": "CODER",
                "timestamp": datetime.now(timezone.utc),
                "logs": "stub code",
                "artifacts": artifacts,
            }
            # Workspace is truth: materialize (exactly what the PiMesh Receiver does).
            for a in artifacts:
                materialize_to_workspace(run_id, a["path"], a.get("content"))
            await transport.publish_response("CODER", payload)

        elif role == "REVIEWER":
            await transport.publish_response("REVIEWER", {
                "protocol_version": "1.0",
                "message_id": f"rev-{task_id}",
                "task_id": task_id,
                "run_id": run_id,
                "state_revision": rev,
                "event": "REVIEW_APPROVED",
                "sender_role": "REVIEWER",
                "timestamp": datetime.now(timezone.utc),
                "logs": "stub review",
            })


async def _run_scenario(negative: bool, with_lockfile: bool):
    tmp = Path(tempfile.mkdtemp())
    fixture = tmp / "fixture"
    fixture.mkdir()
    (fixture / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (fixture / "style.css").write_text(STYLE_RED, encoding="utf-8")
    (fixture / "app.js").write_text(APP_JS, encoding="utf-8")
    if with_lockfile:
        (fixture / "package-lock.json").write_text(LOCK_JSON, encoding="utf-8")
    ws = tmp / "workspace"

    controller, transport = await _build_engine(tmp)
    VerificationRegistry.register("structural_web", WebStructuralVerifier)

    config = {
        "project_name": "Inc", "plan_name": "Inc", "prompt": "x",
        "expected_artifacts": ["index.html", "style.css", "app.js"],
        "acceptance_criteria": ["EXISTS:style.css"],
        "verification_type": "structural_web",
    }
    run_id = await controller.create_run(config)
    setup_ingest_run(run_id, src=str(fixture), workspace_dir=str(ws))
    controller.transport_factory = lambda: transport
    await controller.start_run(run_id)

    worker = asyncio.create_task(_stub_worker(run_id, transport, negative, with_lockfile))
    try:
        final = None
        for _ in range(1800):  # ~90s budget
            st = await controller.get_run_status(run_id)
            if st["status"] in ("COMPLETED", "FAILED", "CANCELLED"):
                final = st
                break
            await asyncio.sleep(0.05)
        if final is None:
            raise RuntimeError(f"run {run_id} did not reach terminal state in time")
        return {
            "run_id": run_id, "final": final, "tmp": tmp, "ws": ws,
            "fixture": fixture, "negative": negative, "with_lockfile": with_lockfile,
            "controller": controller, "config": config,
        }
    finally:
        worker.cancel()
        await controller.stop_run(run_id)


def _workspace_paths(ws: Path, run_id: str):
    ws_root = os.path.join(str(ws), run_id, "project")
    baseline_path = os.path.join(str(ws), run_id, "baseline_manifest.json")
    return ws_root, baseline_path


def _assert_positive(res):
    assert res["final"]["status"] == "COMPLETED", res["final"]
    ws_root, baseline_path = _workspace_paths(res["ws"], res["run_id"])
    current = build_manifest(ws_root)
    baseline = load_manifest(baseline_path)
    diff = diff_manifests(baseline, current)
    assert diff["changed"] == ["style.css"], diff
    assert diff["added"] == [], diff
    assert diff["removed"] == [], diff


def _assert_negative(res, expect_drift_file):
    assert res["final"]["status"] == "FAILED", res["final"]
    ws_root, baseline_path = _workspace_paths(res["ws"], res["run_id"])
    baseline = load_manifest(baseline_path)
    project_files = list(baseline["files"].keys())
    scope = ["style.css"]
    protected = [f for f in project_files if f != "style.css"]
    # Independent, deterministic proof that the drift WOULD be caught by the verifier.
    result = verify_scope(ws_root, baseline_path, scope_files=scope, protected_files=protected)
    assert result.ok is False, result.report
    assert result.code in ("SCOPE_VIOLATION", "PROTECTED_VIOLATION", "WORKSPACE_DRIFT"), result.code
    assert expect_drift_file in result.changed, (expect_drift_file, result.changed)
    # Workspace truth reflects the drift.
    current = build_manifest(ws_root)
    diff = diff_manifests(baseline, current)
    assert expect_drift_file in diff["changed"], diff


async def _assert_archive(res):
    run_id = res["run_id"]
    archiver = RunArchiver(
        archive_runs_dir=res["tmp"] / "archive",
        artifact_dir=res["tmp"] / "artifacts",
    )
    manifest = await archiver.archive_run(run_id, res["controller"], res["config"])
    # manifest pointer file exists
    manifest_path = res["tmp"] / "archive" / run_id / "manifest.json"
    assert manifest_path.exists(), "archive manifest missing"
    # baseline pointer + copy
    assert manifest.get("baseline_manifest") == "baseline_manifest.json"
    base_copy = res["tmp"] / "archive" / run_id / "baseline_manifest.json"
    assert base_copy.exists(), "baseline manifest not archived"
    # workspace + scope pointers
    assert manifest.get("workspace_root")
    summary = manifest.get("scope_summary") or {}
    assert "task-coder-1" in summary, summary
    assert summary["task-coder-1"]["scope_files"] == ["style.css"], summary
    # Phase 4 (Idee C): the archive hook produces a read-only audit report.
    audit_md = res["tmp"] / "archive" / run_id / "audit.md"
    assert audit_md.exists(), "audit.md not produced by archive hook"
    assert (res["tmp"] / "archive" / run_id / "audit.json").exists(), "audit.json missing"
    audit_text = audit_md.read_text(encoding="utf-8")
    assert run_id in audit_text, "run_id missing in audit.md"
    assert "terminal_state: **COMPLETED**" in audit_text, "terminal_state missing in audit.md"
    # Task Table rows (RESEARCHER, PLANNER, CODER, REVIEWER) -> at least 3
    assert audit_text.count("| `") >= 3, "task table rows missing in audit.md"


async def _main():
    failures = []

    # 1) POSITIVE
    try:
        res = await _run_scenario(negative=False, with_lockfile=False)
        _assert_positive(res)
        await _assert_archive(res)
        print("PASS e2e_positive (COMPLETED, diff changed==[style.css], archive baseline pointer)")
    except Exception as e:  # noqa: BLE001
        print(f"FAIL e2e_positive: {e}")
        failures.append("e2e_positive")
    finally:
        pass

    # 2) NEGATIVE (index.html drift)
    try:
        res = await _run_scenario(negative=True, with_lockfile=False)
        _assert_negative(res, "index.html")
        print("PASS e2e_negative (FAILED, index.html drift flagged by scope verifier)")
    except Exception as e:  # noqa: BLE001
        print(f"FAIL e2e_negative: {e}")
        failures.append("e2e_negative")

    # 3) LOCKFILE (package-lock.json drift)
    try:
        res = await _run_scenario(negative=False, with_lockfile=True)
        _assert_negative(res, "package-lock.json")
        print("PASS e2e_lockfile (FAILED, package-lock.json drift flagged)")
    except Exception as e:  # noqa: BLE001
        print(f"FAIL e2e_lockfile: {e}")
        failures.append("e2e_lockfile")

    if failures:
        print(f"\n{len(failures)} FAILURES: {failures}")
        raise SystemExit(1)
    print("\nALL E2E PASS")


if __name__ == "__main__":
    asyncio.run(_main())
