"""
Scheduler — Ingest-Mode CODER Gate (Option 2a).

Run via: ./tools/safe_test.sh tests/test_scheduler_coder_gate.py

These are unit tests for the new serialization gate in engine/scheduler.py.
They avoid SQLAlchemy mocks by testing the pure gating logic separately and
using a real async sqlite DB only for the integration test.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from engine.models import Base, Task, Run, Project, Plan
from engine.repository import MessageRepository
from engine.scheduler import Scheduler, is_coder_gate_blocked
from engine.services.ingest_context import register_ingest, clear_ingest

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# A) Pure unit tests — no DB, no SQLAlchemy
# ---------------------------------------------------------------------------

def test_is_coder_gate_blocked_none_when_no_other_coder():
    assert is_coder_gate_blocked([], "task-1") is None
    assert is_coder_gate_blocked([
        {"id": "task-1", "assigned_role": "CODER", "state": "READY"},
    ], "task-1") is None


def test_is_coder_gate_blocked_blocks_on_non_terminal_coder():
    blocking = is_coder_gate_blocked([
        {"id": "task-1", "assigned_role": "CODER", "state": "CLAIMED"},
        {"id": "task-2", "assigned_role": "CODER", "state": "READY"},
    ], "task-2")
    assert blocking == {"id": "task-1", "state": "CLAIMED"}


def test_is_coder_gate_blocked_ignores_reviewer():
    assert is_coder_gate_blocked([
        {"id": "task-1", "assigned_role": "REVIEWER", "state": "REVIEWING"},
        {"id": "task-2", "assigned_role": "CODER", "state": "READY"},
    ], "task-2") is None


def test_is_coder_gate_blocked_allows_terminal_coder():
    assert is_coder_gate_blocked([
        {"id": "task-1", "assigned_role": "CODER", "state": "COMPLETE"},
        {"id": "task-2", "assigned_role": "CODER", "state": "READY"},
    ], "task-2") is None


def test_is_coder_gate_blocked_multiple_blocking_coders_returns_first():
    blocking = is_coder_gate_blocked([
        {"id": "task-1", "assigned_role": "CODER", "state": "VERIFYING"},
        {"id": "task-2", "assigned_role": "CODER", "state": "REVIEWING"},
        {"id": "task-3", "assigned_role": "CODER", "state": "READY"},
    ], "task-3")
    assert blocking == {"id": "task-1", "state": "VERIFYING"}


# ---------------------------------------------------------------------------
# C) Integration test — real async sqlite DB, no LLM
# ---------------------------------------------------------------------------

class FakeMessenger:
    def __init__(self):
        self.sent = []

    async def __call__(self, payload):
        self.sent.append(payload)


def _make_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}", connect_args={"check_same_thread": False})
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False, class_=AsyncSession)

    async def init():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(init())
    return engine, session_factory, path


async def _with_session(session_factory, fn, *args, **kwargs):
    async with session_factory() as session:
        async with session.begin():
            return await fn(session, *args, **kwargs)


async def _seed_run_project_plan(session, run_id="run-gate-1"):
    run = Run(id=run_id, config_json={"prompt": "ingest test"})
    session.add(run)
    project = Project(id="proj-1", run_id=run_id, name="proj-1", active_plan_id="plan-1")
    session.add(project)
    plan = Plan(id="plan-1", project_id="proj-1", run_id=run_id, name="plan-1", version=1, status="IN_PROGRESS")
    session.add(plan)
    await session.commit()
    return run, project, plan


async def _make_task(session, run_id, plan_id, task_id, role="CODER", state="READY"):
    task = Task(
        id=task_id,
        run_id=run_id,
        plan_id=plan_id,
        description=f"task {task_id}",
        state=state,
        assigned_role=role,
        execution_phase="CODING",
        expected_artifacts=[],
        acceptance_criteria=[],
    )
    session.add(task)
    await session.commit()
    return task


async def _run_tick(scheduler, run_id, session):
    repo = MessageRepository(session)
    await scheduler._handle_assignments(session, repo, run_id)


def test_ingest_coder_tasks_are_serialized_integration():
    engine, session_factory, path = _make_db()
    try:
        async def test():
            await _with_session(session_factory, _seed_run_project_plan, "run-gate-serial")
            register_ingest("run-gate-serial", "/tmp/ws/proj", "/tmp/ws/baseline.json")
            try:
                await _with_session(session_factory, _make_task, "run-gate-serial", "plan-1", "task-1", role="CODER", state="READY")
                await _with_session(session_factory, _make_task, "run-gate-serial", "plan-1", "task-2", role="CODER", state="READY")
                await _with_session(session_factory, _make_task, "run-gate-serial", "plan-1", "task-3", role="CODER", state="READY")

                messenger = FakeMessenger()
                scheduler = Scheduler(session_factory, messenger_callback=messenger)

                async with session_factory() as session:
                    async with session.begin():
                        await _run_tick(scheduler, "run-gate-serial", session)

                coder_sent = [p for p in messenger.sent if p.get("role") == "CODER"]
                assert len(coder_sent) == 1, f"expected 1 CODER dispatch, got {len(coder_sent)}: {[p.get('task_id') for p in coder_sent]}"
                assert coder_sent[0]["task_id"] == "task-1"

                # task-2 and task-3 must NOT dispatch while task-1 is non-terminal
                for tid in ("task-2", "task-3"):
                    assert not any(p.get("task_id") == tid for p in messenger.sent), f"{tid} must be gated"

                # Mark task-1 terminal -> next CODER may dispatch
                async def mark_complete(session):
                    t1 = await session.get(Task, "task-1")
                    t1.state = "COMPLETE"
                    t1.execution_phase = "COMPLETE"
                    await session.commit()
                await _with_session(session_factory, mark_complete)

                messenger.sent.clear()
                async with session_factory() as session:
                    async with session.begin():
                        await _run_tick(scheduler, "run-gate-serial", session)

                coder_sent = [p for p in messenger.sent if p.get("role") == "CODER"]
                assert len(coder_sent) == 1, f"expected 1 CODER dispatch after task-1 complete, got {len(coder_sent)}"
                assert coder_sent[0]["task_id"] == "task-2"
            finally:
                clear_ingest("run-gate-serial")
        asyncio.run(test())
    finally:
        asyncio.run(engine.dispose())
        try:
            os.remove(path)
        except OSError:
            pass


def test_non_ingest_coder_tasks_are_still_serialized_integration():
    engine, session_factory, path = _make_db()
    try:
        async def test():
            await _with_session(session_factory, _seed_run_project_plan, "run-gate-noingest")
            await _with_session(session_factory, _make_task, "run-gate-noingest", "plan-1", "task-1", role="CODER", state="READY")
            await _with_session(session_factory, _make_task, "run-gate-noingest", "plan-1", "task-2", role="CODER", state="READY")

            messenger = FakeMessenger()
            scheduler = Scheduler(session_factory, messenger_callback=messenger)

            async with session_factory() as session:
                async with session.begin():
                    await _run_tick(scheduler, "run-gate-noingest", session)

            coder_sent = [p for p in messenger.sent if p.get("role") == "CODER"]
            assert len(coder_sent) == 1, f"expected 1 CODER dispatch in non-ingest, got {len(coder_sent)}"
            assert coder_sent[0]["task_id"] == "task-1"

            # task-2 must NOT dispatch while task-1 is non-terminal
            assert not any(p.get("task_id") == "task-2" for p in messenger.sent)
        asyncio.run(test())
    finally:
        asyncio.run(engine.dispose())
        try:
            os.remove(path)
        except OSError:
            pass


if __name__ == "__main__":
    failures = []
    for name, fn in [
        ("test_is_coder_gate_blocked_none_when_no_other_coder", test_is_coder_gate_blocked_none_when_no_other_coder),
        ("test_is_coder_gate_blocked_blocks_on_non_terminal_coder", test_is_coder_gate_blocked_blocks_on_non_terminal_coder),
        ("test_is_coder_gate_blocked_ignores_reviewer", test_is_coder_gate_blocked_ignores_reviewer),
        ("test_is_coder_gate_blocked_allows_terminal_coder", test_is_coder_gate_blocked_allows_terminal_coder),
        ("test_is_coder_gate_blocked_multiple_blocking_coders_returns_first", test_is_coder_gate_blocked_multiple_blocking_coders_returns_first),
        ("test_ingest_coder_tasks_are_serialized_integration", test_ingest_coder_tasks_are_serialized_integration),
        ("test_non_ingest_coder_tasks_are_still_serialized_integration", test_non_ingest_coder_tasks_are_still_serialized_integration),
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
