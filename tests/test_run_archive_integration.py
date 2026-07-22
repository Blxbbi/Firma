"""
Phase 1 (Idee D) — RunArchiver INTEGRATION test.

Uses the REAL RunController + real SQLite DB (no LLM provider) to prove the full
archiving path end-to-end: create_run -> mark COMPLETED -> RunArchiver.archive_run
(writes manifest/db_snapshot/config_snapshot/artifact_manifest + exercises the real
controller.get_run_summary against the DB).

The live app run was blocked by free-tier PLANNER HARD TIMEOUTs (provider latency,
unrelated to Phase 1). This test isolates the archiving subsystem from that flakiness.

Run via: ./tools/safe_test.sh tests/test_run_archive_integration.py
"""
import asyncio
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, update

from engine.db import DatabaseManager
from engine.models import Base, Run, Plan, Task
from engine.controller import RunController
from engine.services.run_archive import RunArchiver


async def _main():
    tmp = Path(tempfile.mkdtemp())
    db_path = tmp / "test.db"
    db_manager = DatabaseManager(f"sqlite+aiosqlite:///{db_path}")
    async with db_manager.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    def scheduler_factory(db, messenger_callback=None):
        raise AssertionError("not used in this test")

    def transport_factory():
        raise AssertionError("not used in this test")

    controller = RunController(
        db_manager=db_manager,
        scheduler_factory=scheduler_factory,
        transport_factory=transport_factory,
        execution_service=None,
        sandbox=None,
    )

    config = {"app": "counter", "FIRMA_TRANSPORT": "pimesh"}
    run_id = await controller.create_run(config)

    # simulate terminal state (no provider): COMPLETED + one DONE task
    async with db_manager.session_scope() as session:
        await session.execute(
            update(Run)
            .where(Run.id == run_id)
            .values(status="COMPLETED", started_at=datetime.now(timezone.utc))
        )
        plan_res = await session.execute(select(Plan).filter(Plan.run_id == run_id))
        plan = plan_res.scalars().first()
        task = Task(
            id="task-1",
            run_id=run_id,
            plan_id=plan.id,
            state="DONE",
            execution_phase="CODING",
            assigned_role="CODER",
            state_revision=1,
            expected_artifacts=[],
            acceptance_criteria=[],
            max_retries=3,
        )
        session.add(task)

    # artifact on disk for this run
    artifact_dir = tmp / "artifacts"
    (artifact_dir / run_id / "task-1").mkdir(parents=True)
    (artifact_dir / run_id / "task-1" / "game.js").write_text(
        "console.log(1)", encoding="utf-8"
    )

    archive_dir = tmp / "archive_runs"
    archiver = RunArchiver(
        archive_runs_dir=archive_dir,
        artifact_dir=artifact_dir,
        keep_last_n=20,
        keep_compressed_last_n=100,
    )
    manifest = await archiver.archive_run(run_id, controller, config)

    run_dir = archive_dir / run_id
    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "db_snapshot.json").exists()
    assert (run_dir / "config_snapshot.json").exists()
    assert (run_dir / "artifact_manifest.json").exists()

    assert manifest["terminal_state"] == "COMPLETED"
    assert manifest["app"] == "counter"
    assert manifest["transport"] == "pimesh"
    assert len(manifest["artifact_refs"]) == 1
    assert Path(manifest["artifact_refs"][0]["path"]).exists()
    # real controller.get_run_summary produced task summaries from the DB
    # (create_run seeds a bootstrap PLANNER task, plus our CODER task)
    assert len(manifest["task_summary"]) >= 1
    assert any(t["role"] == "CODER" for t in manifest["task_summary"])
    assert any(t["state"] == "DONE" for t in manifest["task_summary"])
    assert manifest["config_snapshot"]["FIRMA_TRANSPORT"] == "pimesh"
    print("INTEGRATION_OK", run_id)


if __name__ == "__main__":
    asyncio.run(_main())
