"""
F4 Light Integration — surgical edit end-to-end via InternalTransport + StubWorker.

Verifies that when a CODER produces a surgically edited artifact (preserving the
original file's structure, changing only the scoped property), the engine:
  - materializes the edit into the workspace tree
  - scope verifier allows it (only style.css changed)
  - archive + audit capture it correctly
"""
import asyncio
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.controller import RunController
from engine.db import DatabaseManager
from engine.models import Base
from engine.services.ingest import setup_ingest_run
from engine.services.ingest_context import get_ingest, clear_ingest
from engine.transport.internal_transport import InternalTransport
from engine.services.execution import ExecutionService
from engine.services.sandbox import LocalPythonSandbox
from engine.scheduler import Scheduler
from engine.services.verification_registry import VerificationRegistry
from engine.services.verifiers.web_verifier import WebStructuralVerifier
from engine.services.run_archive import RunArchiver
from engine.services.workspace_materializer import materialize_to_workspace

STYLE_ORIGINAL = "button { color: red; border: 1px solid #333; }"
STYLE_SURGICAL = "button { color: #00f; border: 1px solid #333; }"
INDEX_HTML = "<html><head><link rel=\"stylesheet\" href=\"style.css\"></head><body><button>Klick</button><script src=\"app.js\"></script></body></html>"
APP_JS = "console.log('ok');"


async def _build_engine(tmp: Path):
    db_path = tmp / "f4.db"
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


async def _stub_worker(run_id, transport):
    """Deterministic worker: RESEARCHER -> PLANNER -> CODER (surgical) -> REVIEWER."""
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
            brief = "# Research Brief\n\nChange button color to #00f."
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
                    "plan_name": "Surgical CSS Edit",
                    "tasks": [{
                        "id": "task-coder-1",
                        "description": "Change button color to #00f only",
                        "expected_artifacts": [{"path": "style.css", "type": "UPDATE"}],
                        "acceptance_criteria": ["CONTAINS:style.css:#00f"],
                    }],
                },
            })

        elif role == "CODER":
            ing = get_ingest(run_id)
            ws_root = ing["workspace_root"]
            existing_path = os.path.join(ws_root, "style.css")
            existing_content = ""
            if os.path.isfile(existing_path):
                with open(existing_path, "r", encoding="utf-8") as f:
                    existing_content = f.read()
            edited = existing_content.replace("red", "#00f")
            # Workspace is truth: materialize (exactly what the PiMesh Receiver does).
            materialize_to_workspace(run_id, "style.css", edited)
            await transport.publish_response("CODER", {
                "protocol_version": "1.0",
                "message_id": f"code-{task_id}",
                "task_id": task_id,
                "run_id": run_id,
                "state_revision": rev,
                "event": "CODE_SUBMITTED",
                "sender_role": "CODER",
                "timestamp": datetime.now(timezone.utc),
                "logs": "stub surgical edit",
                "artifacts": [{"path": "style.css", "action": "UPDATE", "content": edited}],
            })

        elif role == "REVIEWER":
            await transport.publish_response("REVIEWER", {
                "protocol_version": "1.0",
                "message_id": f"review-{task_id}",
                "task_id": task_id,
                "run_id": run_id,
                "state_revision": rev,
                "event": "REVIEW_APPROVED",
                "sender_role": "REVIEWER",
                "timestamp": datetime.now(timezone.utc),
                "logs": "stub review approved",
                "artifacts": [],
            })


async def run_surgical_edit_e2e():
    tmp = Path(tempfile.mkdtemp(prefix="firma_f4_e2e_"))
    fixture = tmp / "fixture"
    fixture.mkdir()
    (fixture / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (fixture / "style.css").write_text(STYLE_ORIGINAL, encoding="utf-8")
    (fixture / "app.js").write_text(APP_JS, encoding="utf-8")
    ws = tmp / "workspace"

    controller, transport = await _build_engine(tmp)
    VerificationRegistry.register("structural_web", WebStructuralVerifier)

    config = {
        "project_name": "CounterF4",
        "plan_name": "Surgical",
        "prompt": "Change button color to #00f",
        "expected_artifacts": ["style.css"],
        "acceptance_criteria": ["CONTAINS:style.css:#00f"],
        "verification_type": "structural_web",
    }
    run_id = await controller.create_run(config)
    setup_ingest_run(run_id, src=str(fixture), workspace_dir=str(ws))
    controller.transport_factory = lambda: transport
    await controller.start_run(run_id)

    worker = asyncio.create_task(_stub_worker(run_id, transport))
    try:
        final = None
        for _ in range(2400):  # ~120s budget
            st = await controller.get_run_status(run_id)
            if st["status"] in ("COMPLETED", "FAILED", "CANCELLED"):
                final = st
                break
            await asyncio.sleep(0.05)
        if final is None:
            raise RuntimeError(f"run {run_id} did not reach terminal state in time")
    finally:
        worker.cancel()
        await controller.stop_run(run_id)

    assert final["status"] == "COMPLETED", final

    ws_root = os.path.join(str(ws), run_id, "project")
    final_style = open(os.path.join(ws_root, "style.css"), "r", encoding="utf-8").read()
    assert final_style == STYLE_SURGICAL, f"expected surgical edit, got: {final_style!r}"
    assert "red" not in final_style, "original 'red' should be gone"
    assert "#00f" in final_style, "expected #00f in edited style.css"

    # Archive + audit assertions (Phase 1/4)
    archiver = RunArchiver(archive_runs_dir=str(tmp / "archive"), artifact_dir=str(tmp / "artifacts"))
    manifest = await archiver.archive_run(run_id, controller, config)
    # manifest pointer file exists
    manifest_path = tmp / "archive" / run_id / "manifest.json"
    assert manifest_path.exists(), "archive manifest missing"
    # baseline pointer + copy
    assert manifest.get("baseline_manifest") == "baseline_manifest.json"
    base_copy = tmp / "archive" / run_id / "baseline_manifest.json"
    assert base_copy.exists(), "baseline manifest not archived"
    # workspace + scope pointers
    assert manifest.get("workspace_root")
    summary = manifest.get("scope_summary") or {}
    # Phase 4 (Idee C): the archive hook produces a read-only audit report.
    audit_md = tmp / "archive" / run_id / "audit.md"
    assert audit_md.exists(), "audit.md not produced by archive hook"
    assert (tmp / "archive" / run_id / "audit.json").exists(), "audit.json missing"
    audit_text = audit_md.read_text(encoding="utf-8")
    assert run_id in audit_text, "run_id missing in audit.md"
    assert "terminal_state: **COMPLETED**" in audit_text, "terminal_state missing in audit.md"
    # Task Table rows (RESEARCHER, PLANNER, CODER, REVIEWER) -> at least 3
    assert audit_text.count("| `") >= 3, "task table rows missing in audit.md"

    clear_ingest(run_id)
    print("PASS e2e_phase4_ingest_stage")
    return True


if __name__ == "__main__":
    success = asyncio.run(run_surgical_edit_e2e())
    sys.exit(0 if success else 1)
