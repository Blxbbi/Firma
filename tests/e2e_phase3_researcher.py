"""
Phase 3 (Idee B) - E2E: Researcher is read-only, grounds the PLANNER, can't touch project.

Run via: ./tools/safe_test.sh tests/e2e_phase3_researcher.py

Design (deterministic, no LLM - InternalTransport + StubWorker):
  setup_ingest_run -> workspace/<run_id>/project + baseline + registry
  Orchestrator/Scheduler seeds RESEARCHER (before PLANNER, dependency-gated)
  StubWorker:
    RESEARCHER -> writes research/brief.md (allowed); optionally drifts a project file
    PLANNER    -> plan (scope = style.css)
    CODER      -> edits style.css (in scope)
    REVIEWER   -> approve
  Guardian RESEARCH_COMPLETE:
    - artifact-path policy (must be under research/)
    - baseline-diff gate (project/ subtree must be unchanged) -> else FAILED

Scenarios:
  POS : researcher writes only brief -> Run COMPLETED, archive has research_brief pointer
  NEG : researcher ALSO edits index.html -> Run FAILED (drift detected deterministically)
"""
import asyncio
import os
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
from engine.models import Base, Task

STYLE_RED = "button { background: red; }"
STYLE_BLUE = "button { background: blue; }"
INDEX_HTML = "<html><body><button id='b'>Click</button></body></html>"
APP_JS = "console.log('app');"


async def _build_engine(tmp: Path):
    db_path = tmp / "e2e3.db"
    if db_path.exists():
        db_path.unlink()
    dbm = DatabaseManager(f"sqlite+aiosqlite:///{db_path}")
    async with dbm.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    def scheduler_factory(db, messenger_callback=None):
        return Scheduler(db, messenger_callback=messenger_callback)

    transport = InternalTransport()

    def transport_factory():
        return transport

    return RunController(dbm, scheduler_factory, transport_factory, ExecutionService(dbm), LocalPythonSandbox()), transport


async def _stub_worker(run_id, transport, researcher_drift):
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
            ing = get_ingest(run_id)
            ws_root = ing["workspace_root"]
            research_dir = os.path.join(os.path.dirname(ws_root), "research")
            os.makedirs(research_dir, exist_ok=True)
            brief = "# Research Brief\n\nGrounding notes for the planner."
            with open(os.path.join(research_dir, "brief.md"), "w", encoding="utf-8") as f:
                f.write(brief)
            # Negative: researcher ALSO modifies a project file (must be caught)
            if researcher_drift:
                materialize_to_workspace(run_id, "index.html", INDEX_HTML + "<!-- DRIFT -->")
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
            await transport.publish_response("PLANNER", {
                "protocol_version": "1.0",
                "message_id": f"plan-{task_id}",
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
            })

        elif role == "CODER":
            await transport.publish_response("CODER", {
                "protocol_version": "1.0",
                "message_id": f"code-{task_id}-{rev}",
                "task_id": task_id,
                "run_id": run_id,
                "state_revision": rev,
                "event": "CODE_SUBMITTED",
                "sender_role": "CODER",
                "timestamp": datetime.now(timezone.utc),
                "logs": "stub code",
                "artifacts": [{"path": "style.css", "action": "UPDATE", "content": STYLE_BLUE}],
            })
            materialize_to_workspace(run_id, "style.css", STYLE_BLUE)

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


async def _run_scenario(researcher_drift: bool):
    tmp = Path(tempfile.mkdtemp())
    fixture = tmp / "fixture"
    fixture.mkdir()
    (fixture / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (fixture / "style.css").write_text(STYLE_RED, encoding="utf-8")
    (fixture / "app.js").write_text(APP_JS, encoding="utf-8")
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

    worker = asyncio.create_task(_stub_worker(run_id, transport, researcher_drift))
    try:
        final = None
        for _ in range(1800):
            st = await controller.get_run_status(run_id)
            if st["status"] in ("COMPLETED", "FAILED", "CANCELLED"):
                final = st
                break
            await asyncio.sleep(0.05)
        if final is None:
            raise RuntimeError(f"run {run_id} did not reach terminal state in time")
        return {"run_id": run_id, "final": final, "tmp": tmp, "ws": ws, "controller": controller, "config": config}
    finally:
        worker.cancel()
        await controller.stop_run(run_id)


def _workspace_paths(ws: Path, run_id: str):
    ws_root = os.path.join(str(ws), run_id, "project")
    baseline_path = os.path.join(str(ws), run_id, "baseline_manifest.json")
    return ws_root, baseline_path


async def _assert_positive(res):
    assert res["final"]["status"] == "COMPLETED", res["final"]
    ws_root, baseline_path = _workspace_paths(res["ws"], res["run_id"])
    current = build_manifest(ws_root)
    baseline = load_manifest(baseline_path)
    diff = diff_manifests(baseline, current)
    # only the CODER's in-scope edit (style.css) changed; researcher wrote outside project/
    assert diff["changed"] == ["style.css"], diff
    assert diff["added"] == [], diff
    assert diff["removed"] == [], diff

    # Archive: research brief pointer + copy
    archiver = RunArchiver(archive_runs_dir=res["tmp"] / "archive", artifact_dir=res["tmp"] / "artifacts")
    manifest = await archiver.archive_run(res["run_id"], res["controller"], res["config"])
    assert manifest.get("research_brief") == "research_brief.md", manifest
    assert (res["tmp"] / "archive" / res["run_id"] / "research_brief.md").exists(), "research brief not archived"
    assert manifest.get("baseline_manifest") == "baseline_manifest.json"


async def _assert_negative(res):
    assert res["final"]["status"] == "FAILED", res["final"]
    ws_root, baseline_path = _workspace_paths(res["ws"], res["run_id"])
    baseline = load_manifest(baseline_path)
    current = build_manifest(ws_root)
    diff = diff_manifests(baseline, current)
    # Researcher drift on a project file is deterministically detected
    assert "index.html" in diff["changed"], diff


async def _main():
    failures = []

    try:
        res = await _run_scenario(researcher_drift=False)
        await _assert_positive(res)
        print("PASS e2e_researcher_positive (COMPLETED, only style.css changed, archive has research brief)")
    except Exception as e:  # noqa: BLE001
        print(f"FAIL e2e_researcher_positive: {e}")
        failures.append("positive")

    try:
        res = await _run_scenario(researcher_drift=True)
        await _assert_negative(res)
        print("PASS e2e_researcher_negative (FAILED, researcher project-file drift detected)")
    except Exception as e:  # noqa: BLE001
        print(f"FAIL e2e_researcher_negative: {e}")
        failures.append("negative")

    if failures:
        print(f"\n{len(failures)} FAILURES: {failures}")
        raise SystemExit(1)
    print("\nALL E2E PASS")


if __name__ == "__main__":
    asyncio.run(_main())
