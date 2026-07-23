"""
Phase 4 (Idee C) - Unit tests for RunAuditor (deterministic, read-only).

Run via: ./tools/safe_test.sh tests/test_phase4_auditor.py

  test_auditor_generates_markdown_from_manifest_and_db_stub
      -> seeds a real DB (Run+Project+Plan+Tasks+TransitionLogs), writes
         manifest.json + db_snapshot.json + baseline + research_brief,
         asserts audit.md has all 7 sections, correct task count, scope
         recheck, research link, and inferred guards.

  test_auditor_handles_missing_optional_fields_gracefully
      -> minimal manifest (run_id only), no DB tasks, no optional files
         -> audit.md still produced, missing sections shown as n/a.
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
from engine.models import Base, Run, Project, Plan, Task, TaskTransitionLog
from engine.services.auditor import RunAuditor
from engine.services.baseline_manifest import build_manifest


async def _seed_db(tmp: Path, run_id: str, with_tasks: bool, with_failure: bool):
    db_path = tmp / "audit.db"
    if db_path.exists():
        db_path.unlink()
    dbm = DatabaseManager(f"sqlite+aiosqlite:///{db_path}")
    async with dbm.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    started = datetime(2026, 7, 16, 10, 0, 0, tzinfo=timezone.utc)
    completed = datetime(2026, 7, 16, 10, 2, 0, tzinfo=timezone.utc)

    async with dbm.session_scope() as session:
        proj = Project(id="proj-1", run_id=run_id, name="Inc")
        session.add(proj)
        plan = Plan(id="plan-1", run_id=run_id, project_id="proj-1", version=1, name="Inc", status="COMPLETED")
        session.add(plan)
        run = Run(id=run_id, status="COMPLETED", started_at=started, completed_at=completed,
                  failure_reason=None)
        session.add(run)
        if with_tasks:
            tasks = [
                Task(id="T1", run_id=run_id, plan_id="plan-1", state="COMPLETE",
                     execution_phase="RESEARCHING", assigned_role="RESEARCHER",
                     attempt_count=1, verification_type="research_readonly",
                     expected_artifacts=[], acceptance_criteria=[]),
                Task(id="T2", run_id=run_id, plan_id="plan-1", state="COMPLETE",
                     execution_phase="PLANNING", assigned_role="PLANNER",
                     attempt_count=1, verification_type="structural_web",
                     expected_artifacts=[], acceptance_criteria=[]),
                Task(id="T3", run_id=run_id, plan_id="plan-1", state="COMPLETE",
                     execution_phase="CODING", assigned_role="CODER",
                     attempt_count=1, verification_type="structural_web",
                     expected_artifacts=[], acceptance_criteria=[]),
                Task(id="T6", run_id=run_id, plan_id="plan-1", state="COMPLETE",
                     execution_phase="REVIEWING", assigned_role="REVIEWER",
                     attempt_count=1, verification_type="structural_web",
                     expected_artifacts=[], acceptance_criteria=[]),
            ]
            if with_failure:
                tasks += [
                    Task(id="T4", run_id=run_id, plan_id="plan-1", state="FAILED",
                         execution_phase="VERIFYING", assigned_role="CODER",
                         attempt_count=2, retry_count=1, verification_type="structural_web",
                         last_review_feedback="scope violation on index.html",
                         expected_artifacts=[], acceptance_criteria=[]),
                    Task(id="T5", run_id=run_id, plan_id="plan-1", state="FAILED",
                         execution_phase="CODING", assigned_role="CODER",
                         attempt_count=1, verification_type="structural_web",
                         expected_artifacts=[], acceptance_criteria=[]),
                ]
                session.add_all(tasks)
                session.add(TaskTransitionLog(task_id="T4", from_phase="VERIFYING",
                                              event="VERIFY_FAILURE", to_phase="VERIFYING",
                                              sender_role="VERIFIER", previous_revision=1,
                                              new_revision=2, message_id="m4",
                                              timestamp=datetime(2026, 7, 16, 10, 1, 30, tzinfo=timezone.utc)))
                session.add(TaskTransitionLog(task_id="T5", from_phase="CODING",
                                              event="WORKER_TIMEOUT", to_phase="CODING",
                                              sender_role="KERNEL", previous_revision=1,
                                              new_revision=1, message_id="m5",
                                              timestamp=datetime(2026, 7, 16, 10, 1, 45, tzinfo=timezone.utc)))
            else:
                session.add_all(tasks)
    return dbm


class _StubController:
    def __init__(self, dbm, status):
        self.db = dbm
        self._status = status

    async def get_run_status(self, run_id):
        return self._status


async def _test_generates_markdown():
    tmp = Path(tempfile.mkdtemp())
    run_id = "run-audit-001"
    dbm = await _seed_db(tmp, run_id, with_tasks=True, with_failure=True)
    run_dir = tmp / "archive" / run_id
    run_dir.mkdir(parents=True)

    # project + baseline for the scope re-check
    project_dir = tmp / "project"
    project_dir.mkdir()
    (project_dir / "style.css").write_text("button { color: red; }", encoding="utf-8")
    (project_dir / "index.html").write_text("<html></html>", encoding="utf-8")
    (project_dir / "app.js").write_text("console.log(1)", encoding="utf-8")
    baseline = build_manifest(str(project_dir))
    import json
    (run_dir / "baseline_manifest.json").write_text(
        json.dumps(baseline, indent=2, ensure_ascii=False), encoding="utf-8")

    (run_dir / "research_brief.md").write_text(
        "# Research Brief\nThe button should be blue, not red.", encoding="utf-8")

    manifest = {
        "run_id": run_id,
        "app": "Inc",
        "transport": "InternalTransport",
        "terminal_state": "COMPLETED",
        "started_at": "2026-07-16T10:00:00+00:00",
        "config_snapshot": {
            "FIRMA_APP": "Inc", "FIRMA_TRANSPORT": "InternalTransport",
            "SESSION_MODE": "default", "FIRMA_PERSONA_ID": "base",
        },
        "scope_summary": {
            "T3": {"scope_files": ["style.css"], "protected_files": ["index.html", "app.js"]},
        },
        "artifact_refs": [{"path": f"workspace/{run_id}/project/style.css", "bytes": 24, "task_id": "T3"}],
        "tool_usage_by_task": {
            "T1": {"read": 2},
            "T3": {"read": 3, "write": 1, "edit": 1, "bash": 1},
            "T6": {"read": 1, "write": 1, "edit": 2, "bash": 1},
        },
        "workspace_root": str(project_dir),
        "baseline_manifest": "baseline_manifest.json",
        "research_brief": "research_brief.md",
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (run_dir / "db_snapshot.json").write_text(json.dumps({
        "run_id": run_id, "terminal_state": "COMPLETED",
        "task_summary": [], "failure_reason": None, "summary_counters": {},
    }), encoding="utf-8")

    status = {
        "run_id": run_id, "status": "COMPLETED",
        "started_at": "2026-07-16T10:00:00+00:00",
        "completed_at": "2026-07-16T10:02:00+00:00",
        "failure_reason": None,
    }
    controller = _StubController(dbm, status)
    report = await RunAuditor().write_report(run_id, run_dir, controller)

    md = (run_dir / "audit.md").read_text(encoding="utf-8")
    assert (run_dir / "audit.json").exists(), "audit.json missing"

    # all 9 sections present (incl. tool usage + policy checks)
    for sec in [
        "## 1. Run Overview", "## 2. Task Table", "## 3. Scope / Drift Summary",
        "## 4. Research Summary", "## 5. Failures & Retries",
        "## 6. Artifacts / Deliverable pointers", "## 7. Repro Commands",
        "## 8. Tool Usage by Role", "## 9. Tool Policy Checks",
    ]:
        assert sec in md, f"missing section {sec}"


    # run_id + task count (6 tasks)
    assert run_id in md
    assert md.count("| `T") == 6, f"expected 6 task rows, got {md.count('| `T')}"

    # scope recheck ran (workspace + baseline available)
    assert "recheck:" in md, "scope recheck not shown"

    # research link present
    assert "research_brief.md" in md

    # inferred guards for the two failed tasks
    assert "verifier_guard" in md, "verifier_guard not inferred"
    assert "worker_timeout_guard" in md, "worker_timeout_guard not inferred"

    # tool usage present (from manifest)
    assert "## 8. Tool Usage by Role" in md
    assert "- `read`: 2" in md, "expected aggregated read counts"

    # policy checks: reviewer T6 has edit/bash violations
    assert "## 9. Tool Policy Checks" in md
    assert "POLICY VIOLATION" in md, "expected policy violation for reviewer T6 edit/bash"
    assert "T6" in md

    # duration computed
    assert "duration_seconds: 120" in md, "duration not computed"

    # repro env
    assert "FIRMA_APP=Inc" in md


async def _test_missing_optional_fields_graceful():
    tmp = Path(tempfile.mkdtemp())
    run_id = "run-audit-002"
    dbm = await _seed_db(tmp, run_id, with_tasks=False, with_failure=False)
    run_dir = tmp / "archive" / run_id
    run_dir.mkdir(parents=True)

    # minimal manifest: only run_id
    import json
    (run_dir / "manifest.json").write_text(json.dumps({"run_id": run_id}), encoding="utf-8")

    status = {"run_id": run_id, "status": "UNKNOWN", "started_at": None,
              "completed_at": None, "failure_reason": None}
    controller = _StubController(dbm, status)

    # must not raise
    report = await RunAuditor().write_report(run_id, run_dir, controller)
    md = (run_dir / "audit.md").read_text(encoding="utf-8")

    assert "Run Audit: run-audit-002" in md
    assert "no tasks recorded" in md
    assert "no research phase" in md
    assert "no ingest/scope data" in md
    assert "(no FIRMA_* env captured)" in md


async def _test_marks_policy_violation_for_reviewer_edit_bash():
    tmp = Path(tempfile.mkdtemp())
    run_id = "run-audit-policy"
    dbm = await _seed_db(tmp, run_id, with_tasks=True, with_failure=False)
    run_dir = tmp / "archive" / run_id
    run_dir.mkdir(parents=True)

    import json
    (run_dir / "manifest.json").write_text(json.dumps({
        "run_id": run_id,
        "app": "Inc",
        "transport": "InternalTransport",
        "terminal_state": "COMPLETED",
        "started_at": "2026-07-16T10:00:00+00:00",
        "config_snapshot": {},
        # T6 is the REVIEWER task in _seed_db(with_failure=False)
        "tool_usage_by_task": {
            "T6": {"read": 1, "write": 1, "edit": 2, "bash": 1},
        },
    }, indent=2), encoding="utf-8")
    (run_dir / "db_snapshot.json").write_text(json.dumps({
        "run_id": run_id, "terminal_state": "COMPLETED",
        "task_summary": [], "failure_reason": None, "summary_counters": {},
    }), encoding="utf-8")

    status = {"run_id": run_id, "status": "COMPLETED",
              "started_at": "2026-07-16T10:00:00+00:00",
              "completed_at": "2026-07-16T10:02:00+00:00",
              "failure_reason": None}
    controller = _StubController(dbm, status)
    report = await RunAuditor().write_report(run_id, run_dir, controller)
    md = (run_dir / "audit.md").read_text(encoding="utf-8")

    assert "## 8. Tool Usage by Role" in md
    assert "## 9. Tool Policy Checks" in md
    assert "POLICY VIOLATION" in md
    # T6 is REVIEWER with edit=2, bash=1 -> violations in JSON report
    for chk in report["tool_policy_checks"]:
        if chk["role"] == "REVIEWER":
            assert chk["ok"] is False
            assert "forbidden_tool:edit=2" in chk["policy_violations"]
            assert "forbidden_tool:bash=1" in chk["policy_violations"]
            break
    else:
        raise AssertionError("REVIEWER policy check not found")
    assert report["tool_policy_checks"]
    for chk in report["tool_policy_checks"]:
        if chk["role"] == "REVIEWER":
            assert chk["ok"] is False
            assert "forbidden_tool:edit=" in str(chk["policy_violations"])
            break
    else:
        raise AssertionError("REVIEWER policy check not found")

async def _main():
    failures = []
    for name, coro in [
        ("generates_markdown", _test_generates_markdown()),
        ("missing_optional_fields", _test_missing_optional_fields_graceful()),
        ("policy_violation", _test_marks_policy_violation_for_reviewer_edit_bash()),
    ]:
        try:
            await coro
            print(f"PASS {name}")
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {name}: {e}")
            failures.append(name)
    if failures:
        print(f"\n{len(failures)} FAILURES: {failures}")
        raise SystemExit(1)
    print("\nALL AUDITOR UNIT TESTS PASS")


if __name__ == "__main__":
    asyncio.run(_main())
