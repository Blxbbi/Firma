"""
Phase 3 (Idee B) - Step3.1: RESEARCHER role + routing (own task before PLANNER).

Run via: ./tools/safe_test.sh tests/test_phase3_researcher_routing.py

Covers:
  - Governance FSM: (RESEARCHING, RESEARCH_COMPLETE) -> (COMPLETE, None) and role auth.
  - create_run seeds a RESEARCHER task (phase RESEARCHING) BEFORE the PLANNER task,
    and the PLANNER depends on the RESEARCHER.
  - Scheduler dependency gating: PLANNER is NOT dispatchable until RESEARCHER is COMPLETE.
"""
import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, update

from engine.db import DatabaseManager
from engine.controller import RunController
from engine.scheduler import Scheduler
from engine.transport.internal_transport import InternalTransport
from engine.services.execution import ExecutionService
from engine.services.sandbox import LocalPythonSandbox
from engine.services.verification_registry import VerificationRegistry
from engine.services.verifiers.web_verifier import WebStructuralVerifier
from engine.repository import MessageRepository
from engine.models import Base, Task, ExecutionPhase, AssignedRole, TaskEvent
from engine.governance import GovernanceMatrix


async def _build(tmp: Path):
    db_path = tmp / "p3.db"
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

    es = ExecutionService(dbm)
    sb = LocalPythonSandbox()
    return RunController(dbm, scheduler_factory, transport_factory, es, sb)


def test_governance_researcher_transition():
    res = GovernanceMatrix.transition(ExecutionPhase.RESEARCHING, TaskEvent.RESEARCH_COMPLETE)
    assert res.next_phase == ExecutionPhase.COMPLETE, res
    assert res.next_role is None, res
    assert GovernanceMatrix.authorize_event(
        ExecutionPhase.RESEARCHING, AssignedRole.RESEARCHER, TaskEvent.RESEARCH_COMPLETE
    ) is True
    # Negative: CODER must NOT be able to complete research
    assert GovernanceMatrix.authorize_event(
        ExecutionPhase.RESEARCHING, AssignedRole.CODER, TaskEvent.RESEARCH_COMPLETE
    ) is False


async def _test_create_run_and_gating():
    tmp = Path(tempfile.mkdtemp())
    c = await _build(tmp)
    VerificationRegistry.register("structural_web", WebStructuralVerifier)
    config = {
        "project_name": "P", "plan_name": "Pl", "prompt": "x",
        "expected_artifacts": ["index.html"],
        "acceptance_criteria": ["EXISTS:index.html"],
        "verification_type": "structural_web",
    }
    run_id = await c.create_run(config)

    async with c.db.session_scope() as session:
        tasks = (await session.execute(select(Task).filter(Task.run_id == run_id))).scalars().all()
        by_role = {t.assigned_role: t for t in tasks}
        assert "RESEARCHER" in by_role, [t.assigned_role for t in tasks]
        r = by_role["RESEARCHER"]
        assert r.execution_phase == "RESEARCHING", r.execution_phase
        p = by_role["PLANNER"]
        assert p.execution_phase == "PLANNING", p.execution_phase
        assert p.dependencies == [r.id], p.dependencies
        plan_id = r.plan_id

        # Dependency gating: only RESEARCHER dispatchable initially
        ready = await MessageRepository(session).get_unassigned_ready_tasks(session, run_id, plan_id)
        roles = [t.assigned_role for t in ready]
        assert "RESEARCHER" in roles, roles
        assert "PLANNER" not in roles, roles

    # Mark researcher COMPLETE -> planner becomes dispatchable
    async with c.db.session_scope() as session:
        await session.execute(
            update(Task).where(Task.id == r.id).values(execution_phase="COMPLETE", state="DONE")
        )

    async with c.db.session_scope() as session:
        ready2 = await MessageRepository(session).get_unassigned_ready_tasks(session, run_id, plan_id)
        roles2 = [t.assigned_role for t in ready2]
        assert "PLANNER" in roles2, roles2


if __name__ == "__main__":
    failures = []
    try:
        test_governance_researcher_transition()
        print("PASS test_governance_researcher_transition")
    except Exception as e:  # noqa: BLE001
        print(f"FAIL test_governance_researcher_transition: {e}")
        failures.append("gov")

    try:
        asyncio.run(_test_create_run_and_gating())
        print("PASS test_create_run_and_gating (researcher before planner + dependency gating)")
    except Exception as e:  # noqa: BLE001
        print(f"FAIL test_create_run_and_gating: {e}")
        failures.append("seed")

    if failures:
        print(f"{len(failures)} FAILURES: {failures}")
        raise SystemExit(1)
    print("OK")
