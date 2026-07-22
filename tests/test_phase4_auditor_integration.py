"""
Phase 4 (Idee C) - Light integration: RunArchiver.archive_run triggers the Auditor.

Run via: ./tools/safe_test.sh tests/test_phase4_auditor_integration.py

Seeds a real DB (Run + Tasks, all COMPLETE), calls RunArchiver.archive_run()
with a minimal stub controller, then asserts that audit.md was produced inside
the archive and contains run_id + terminal_state + task count. This proves the
integration point (archive is the single source that the Auditor hangs off).
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
from engine.models import Base, Run, Project, Plan, Task
from engine.services.run_archive import RunArchiver


async def _seed(tmp: Path, run_id: str):
    db_path = tmp / "integ.db"
    if db_path.exists():
        db_path.unlink()
    dbm = DatabaseManager(f"sqlite+aiosqlite:///{db_path}")
    async with dbm.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    started = datetime(2026, 7, 16, 11, 0, 0, tzinfo=timezone.utc)
    completed = datetime(2026, 7, 16, 11, 3, 0, tzinfo=timezone.utc)
    async with dbm.session_scope() as session:
        session.add(Project(id="proj-1", run_id=run_id, name="Inc"))
        session.add(Plan(id="plan-1", run_id=run_id, project_id="proj-1", version=1, name="Inc", status="COMPLETED"))
        session.add(Run(id=run_id, status="COMPLETED", started_at=started, completed_at=completed, failure_reason=None))
        for i, (tid, role, phase) in enumerate([
            ("T1", "RESEARCHER", "RESEARCHING"),
            ("T2", "PLANNER", "PLANNING"),
            ("T3", "CODER", "CODING"),
            ("T4", "REVIEWER", "REVIEWING"),
        ], start=1):
            session.add(Task(id=tid, run_id=run_id, plan_id="plan-1", state="COMPLETE",
                             execution_phase=phase, assigned_role=role, attempt_count=1,
                             verification_type="structural_web",
                             expected_artifacts=[], acceptance_criteria=[]))
    return dbm


class _StubController:
    def __init__(self, dbm):
        self.db = dbm

    async def get_run_status(self, run_id):
        async with self.db.session_scope() as session:
            from engine.models import Run as _Run
            r = (await session.execute(select(_Run).filter(_Run.id == run_id))).scalars().first()
            return {
                "run_id": r.id, "status": r.status,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "failure_reason": r.failure_reason,
            }

    async def get_run_summary(self, run_id):
        async with self.db.session_scope() as session:
            tasks = list((await session.execute(select(Task).filter(Task.run_id == run_id))).scalars().all())
            task_summary = [{"task_id": t.id, "role": t.assigned_role, "state": t.state,
                             "execution_phase": t.execution_phase, "review": None} for t in tasks]
            return {
                "started_at": None, "terminal_state": "COMPLETED",
                "task_summary": task_summary, "failure_reason": None,
                "summary_counters": {"total": len(tasks), "done": len(tasks), "failed": 0, "review_feedback": 0},
            }


def _write_worker_log(path: Path, tool_counts: dict) -> None:
    import json
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for tool, count in tool_counts.items():
        for _ in range(count):
            lines.append(json.dumps({"type": "tool_execution_start", "toolName": tool}))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def _test_tool_usage_table_in_audit_md():
    tmp = Path(tempfile.mkdtemp())
    run_id = "run-audit-integ-tools"
    dbm = await _seed(tmp, run_id)
    controller = _StubController(dbm)
    config = {"app": "Inc", "FIRMA_TRANSPORT": "InternalTransport", "project_name": "Inc"}

    # Create fake worker.log files under a temp pimesh tree
    pimesh_root = tmp / "pimesh"
    _write_worker_log(
        pimesh_root / "planning-crew" / ".pi" / "work" / run_id / "T1" / "worker.log",
        {"read": 2},
    )
    _write_worker_log(
        pimesh_root / "planning-crew" / ".pi" / "work" / run_id / "T2" / "worker.log",
        {"read": 3, "write": 1},
    )
    _write_worker_log(
        pimesh_root / "coding-crew" / ".pi" / "work" / run_id / "T3" / "worker.log",
        {"read": 5, "write": 2, "edit": 1, "bash": 1},
    )
    _write_worker_log(
        pimesh_root / "reviewing-crew" / ".pi" / "work" / run_id / "T4" / "worker.log",
        {"read": 4, "write": 1, "edit": 2, "bash": 1},
    )

    archiver = RunArchiver(archive_runs_dir=tmp / "archive", artifact_dir=tmp / "artifacts")

    # Temporarily point the archiver at our fake project root
    # (PIMESH_CREWS already contains 'pimesh/...', so BASE_DIR must be tmp, not tmp/pimesh)
    import engine.services.run_archive as _ra
    original_base = _ra.BASE_DIR
    _ra.BASE_DIR = str(tmp)
    try:
        manifest = await archiver.archive_run(run_id, controller, config)
    finally:
        _ra.BASE_DIR = original_base

    run_dir = tmp / "archive" / run_id
    md = (run_dir / "audit.md").read_text(encoding="utf-8")

    assert "## 8. Tool Usage by Role" in md, "tool usage section missing"
    assert "## 9. Tool Policy Checks" in md, "tool policy checks section missing"

    # Aggregated counts by role
    assert "- `read`: 2" in md, "expected aggregated researcher/planner read count"
    assert "- `read`: 4" in md, "expected aggregated reviewer read count"

    # Policy violation for REVIEWER T4 (edit + bash are forbidden for reviewer)
    assert "POLICY VIOLATION" in md, "expected policy violation for reviewer"
    assert "T4" in md, "expected reviewer task id in audit"

    # manifest should carry the raw per-task breakdown
    assert manifest.get("tool_usage_by_task"), "manifest missing tool_usage_by_task"
    assert manifest["tool_usage_by_task"].get("T4"), "manifest missing T4 tool usage"

    print("PASS tool_usage_table_in_audit_md (sections + aggregated counts + policy violation)")


async def _test_auditor_runs_after_archive():
    tmp = Path(tempfile.mkdtemp())
    run_id = "run-audit-integ-001"
    dbm = await _seed(tmp, run_id)
    controller = _StubController(dbm)
    config = {"app": "Inc", "FIRMA_TRANSPORT": "InternalTransport", "project_name": "Inc"}

    archiver = RunArchiver(archive_runs_dir=tmp / "archive", artifact_dir=tmp / "artifacts")
    manifest = await archiver.archive_run(run_id, controller, config)

    run_dir = tmp / "archive" / run_id
    assert (run_dir / "manifest.json").exists(), "manifest.json missing"
    assert (run_dir / "audit.md").exists(), "audit.md not produced by archive hook"

    md = (run_dir / "audit.md").read_text(encoding="utf-8")
    assert run_id in md, "run_id missing in audit.md"
    assert "terminal_state: **COMPLETED**" in md, "terminal_state missing in audit.md"
    # 4 seeded tasks -> 4 rows
    assert md.count("| `T") == 4, f"expected 4 task rows, got {md.count('| `T')}"
    print("PASS auditor_runs_after_archive (audit.md present, run_id+state+tasks in archive)")


async def _main():
    failures = []
    for name, coro in [
        ("auditor_runs_after_archive", _test_auditor_runs_after_archive()),
        ("tool_usage_table_in_audit_md", _test_tool_usage_table_in_audit_md()),
    ]:
        try:
            await coro
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {name}: {e}")
            failures.append(name)
    if failures:
        print(f"\nFAILURES: {failures}")
        raise SystemExit(1)
    print("\nALL AUDITOR INTEGRATION TESTS PASS")


if __name__ == "__main__":
    asyncio.run(_main())
