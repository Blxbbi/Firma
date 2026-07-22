"""
Phase 3 (Idee B) - Step3.2: Research output contract (unit + light integration).

Run via: ./tools/safe_test.sh tests/test_phase3_researcher_contract.py

Covers:
  - Researcher artifacts must be under research/ (path policy), else contract violation.
  - Guardian end-to-end: a valid RESEARCH_COMPLETE transitions the RESEARCHER task
    to COMPLETE; an out-of-policy artifact keeps it in RESEARCHING (retry).
"""
import asyncio
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
from engine.services.artifact_store import ArtifactStore
from engine.services.guardian import GuardianPipeline
from engine.models import Base, Task


async def _build(tmp: Path):
    db_path = tmp / "p3c.db"
    if db_path.exists():
        db_path.unlink()
    dbm = DatabaseManager(f"sqlite+aiosqlite:///{db_path}")
    async with dbm.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    def scheduler_factory(db, cb):
        return Scheduler(db, messenger_callback=cb)

    transport = InternalTransport()

    def transport_factory():
        return transport

    return RunController(dbm, scheduler_factory, transport_factory, ExecutionService(dbm), LocalPythonSandbox())


def _research_payload(run_id, task_id, rev, artifacts):
    return {
        "protocol_version": "1.0",
        "message_id": f"resp-{task_id}",
        "task_id": task_id,
        "run_id": run_id,
        "state_revision": rev,
        "event": "RESEARCH_COMPLETE",
        "sender_role": "RESEARCHER",
        "timestamp": datetime.now(timezone.utc),
        "artifacts": artifacts,
    }


def test_validate_researcher_artifacts():
    g = GuardianPipeline(ArtifactStore())

    class R:
        pass

    rv = R()
    # valid: under research/
    rv.artifacts = [{"path": "research/brief.md", "action": "CREATE", "content": "# Brief"}]
    ok, code = g._validate_researcher_artifacts(rv)
    assert ok, code

    # invalid: writes a project file
    rv.artifacts = [{"path": "index.html", "action": "UPDATE", "content": "x"}]
    ok, code = g._validate_researcher_artifacts(rv)
    assert (not ok) and "RESEARCH_DIR" in code, code

    # invalid: missing artifacts
    rv.artifacts = []
    ok, code = g._validate_researcher_artifacts(rv)
    assert not ok, code

    # invalid: absolute path
    rv.artifacts = [{"path": "/etc/passwd", "action": "CREATE", "content": "x"}]
    ok, code = g._validate_researcher_artifacts(rv)
    assert not ok, code


async def _test_researcher_valid_completes():
    tmp = Path(tempfile.mkdtemp())
    c = await _build(tmp)
    VerificationRegistry.register("structural_web", WebStructuralVerifier)
    run_id = await c.create_run({
        "project_name": "P", "plan_name": "Pl", "prompt": "x",
        "expected_artifacts": ["index.html"], "acceptance_criteria": ["EXISTS:index.html"],
        "verification_type": "structural_web",
    })
    async with c.db.session_scope() as session:
        r = (await session.execute(
            select(Task).filter(Task.run_id == run_id, Task.assigned_role == "RESEARCHER")
        )).scalars().first()
        guardian = GuardianPipeline(ArtifactStore())
        ok, reason = await guardian.process_response(
            session,
            _research_payload(run_id, r.id, r.state_revision,
                              [{"path": "research/brief.md", "action": "CREATE", "content": "# Brief"}]),
            run_id=run_id,
        )
        await session.refresh(r)
        assert r.execution_phase == "COMPLETE", (r.execution_phase, reason, ok)


async def _test_researcher_invalid_retries():
    tmp = Path(tempfile.mkdtemp())
    c = await _build(tmp)
    VerificationRegistry.register("structural_web", WebStructuralVerifier)
    run_id = await c.create_run({
        "project_name": "P", "plan_name": "Pl", "prompt": "x",
        "expected_artifacts": ["index.html"], "acceptance_criteria": ["EXISTS:index.html"],
        "verification_type": "structural_web",
    })
    async with c.db.session_scope() as session:
        r = (await session.execute(
            select(Task).filter(Task.run_id == run_id, Task.assigned_role == "RESEARCHER")
        )).scalars().first()
        guardian = GuardianPipeline(ArtifactStore())
        ok, reason = await guardian.process_response(
            session,
            _research_payload(run_id, r.id, r.state_revision,
                              [{"path": "index.html", "action": "UPDATE", "content": "drift"}]),
            run_id=run_id,
        )
        await session.refresh(r)
        # contract violation -> stays in RESEARCHING (retry), not COMPLETE
        assert r.execution_phase == "RESEARCHING", (r.execution_phase, reason, ok)


if __name__ == "__main__":
    failures = []
    try:
        test_validate_researcher_artifacts()
        print("PASS test_validate_researcher_artifacts")
    except Exception as e:  # noqa: BLE001
        print(f"FAIL test_validate_researcher_artifacts: {e}")
        failures.append("validate")

    try:
        asyncio.run(_test_researcher_valid_completes())
        print("PASS test_researcher_valid_completes (RESEARCH_COMPLETE -> COMPLETE)")
    except Exception as e:  # noqa: BLE001
        print(f"FAIL test_researcher_valid_completes: {e}")
        failures.append("valid")

    try:
        asyncio.run(_test_researcher_invalid_retries())
        print("PASS test_researcher_invalid_retries (out-of-policy artifact -> RESEARCHING)")
    except Exception as e:  # noqa: BLE001
        print(f"FAIL test_researcher_invalid_retries: {e}")
        failures.append("invalid")

    if failures:
        print(f"{len(failures)} FAILURES: {failures}")
        raise SystemExit(1)
    print("OK")
