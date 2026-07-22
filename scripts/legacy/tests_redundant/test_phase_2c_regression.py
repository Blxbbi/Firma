import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Tuple, List, Dict, Any, Optional

from engine.db import DatabaseManager
from engine.models import Base, Task, ExecutionPhase, AssignedRole, TaskEvent, TaskTransitionLog, Project, Plan
from engine.repository import MessageRepository
from engine.services.guardian import GuardianPipeline
from engine.services.artifact_store import ArtifactStore
from engine.transport.pimessenger import PiMessengerTransport, TransportMessage
from engine.orchestrator import Orchestrator
from pydantic import BaseModel

# Logging Configuration
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger("Phase2C-Regression")

class PipelineState(BaseModel):
    phase: ExecutionPhase
    role: Optional[AssignedRole]
    revision: int
    transitions: int

async def get_current_state(session, task_id):
    repo = MessageRepository()
    task = repo.get_task_by_id(session, task_id)
    trans_count = session.query(TaskTransitionLog).filter(TaskTransitionLog.task_id == task_id).count()
    return PipelineState(
        phase=ExecutionPhase(task.execution_phase),
        role=AssignedRole(task.assigned_role) if task.assigned_role else None,
        revision=task.state_revision,
        transitions=trans_count
    )

class MockWorker:
    """Simulates an external worker interacting via NATS."""
    def __init__(self, role: AssignedRole, transport: PiMessengerTransport):
        self.role = role
        self.transport = transport

    async def submit_response(self, task_id: str, event: TaskEvent, revision: int, artifacts: Dict = None):
        payload = {
            "protocol_version": "1.0",
            "message_id": f"msg-{uuid.uuid4().hex[:6]}",
            "task_id": task_id,
            "state_revision": revision,
            "event": event.value,
            "sender_role": self.role.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "artifacts": artifacts or {}
        }
        await self.transport.publish_response(
            role=self.role.value,
            payload=payload
        )
        logger.info(f"[Worker {self.role}] Sent {event} for {task_id} (Rev {revision})")

async def run_regression_test():
    """
    Phase 2C Regression Test: Testing cyclical stability.
    Flow: CODING -> VERIFYING -> REVIEWING -> CODING -> VERIFYING -> REVIEWING -> COMPLETE
    """
    logger.info("--- STARTING PHASE 2C REGRESSION & CYCLICITY TEST ---")
    
    task_id = "T-REGRESS-01"
    db_url = "sqlite:///mesh_regression.db"
    db_manager = DatabaseManager(db_url)
    Base.metadata.drop_all(db_manager.engine)
    Base.metadata.create_all(db_manager.engine)
    
    transport = PiMessengerTransport(nats_url="nats://localhost:4222")
    await transport.connect()
    
    class MockScheduler:
        def assign_unassigned_ready_tasks(self): pass
    class MockExecutionService: pass
    class MockSandbox: pass
    
    scheduler = MockScheduler()
    exec_service = MockExecutionService()
    sandbox = MockSandbox()
    
    orchestrator = Orchestrator(
        db_manager=db_manager, 
        scheduler=scheduler, 
        transport=transport, 
        execution_service=exec_service, 
        sandbox=sandbox
    )
    
    coder = MockWorker(AssignedRole.CODER, transport)
    system = MockWorker(AssignedRole.SYSTEM, transport)
    reviewer = MockWorker(AssignedRole.REVIEWER, transport)
    
    with db_manager.session_scope() as session:
        project = Project(id="P-REGRESS", name="Regression Project")
        session.add(project)
        session.flush()
        plan = Plan(id="PL-REGRESS", project_id=project.id, version=1, name="Regress Plan", status="IN_PROGRESS")
        session.add(plan)
        session.flush()
        project.active_plan_id = plan.id
        task = Task(
            id=task_id, 
            plan_id=plan.id, 
            state="READY", 
            execution_phase=ExecutionPhase.CODING, 
            assigned_role=AssignedRole.CODER, 
            state_revision=0, 
            expected_artifacts=[], 
            acceptance_criteria=[]
        )
        session.add(task)
        session.commit()

    orchestrator_task = asyncio.create_task(orchestrator.run_forever())
    await asyncio.sleep(1)

    async def wait_for_state(expected_rev: int, timeout=5):
        start = asyncio.get_event_loop().time()
        while (asyncio.get_event_loop().time() - start) < timeout:
            with db_manager.session_scope() as session:
                state = await get_current_state(session, task_id)
                if state.revision == expected_rev:
                    return state
            await asyncio.sleep(0.1)
        raise TimeoutError(f"Timed out waiting for revision {expected_rev}")

    try:
        # --- HAPPY PATH: CYCLE 1 (The Failure) ---
        logger.info("Executing Cycle 1: CODING -> VERIFYING -> REVIEWING -> CODING")
        await coder.submit_response(task_id, TaskEvent.CODE_SUBMITTED, 0)
        await wait_for_state(1)
        await system.submit_response(task_id, TaskEvent.VERIFY_SUCCESS, 1)
        await wait_for_state(2)
        await reviewer.submit_response(task_id, TaskEvent.REVIEW_FAILURE, 2)
        state = await wait_for_state(3)
        logger.info(f"Cycle 1 Complete. State: {state}")
        assert state.phase == ExecutionPhase.CODING
        assert state.role == AssignedRole.CODER

        # --- NEGATIVE MATRIX: INTERLEAVED AT REGRESSION POINT ---
        logger.info("Running Negative Tests at Regression Point (Rev 3)...")
        
        async def assert_rejected(event: TaskEvent, role: AssignedRole, rev: int, label: str):
            with db_manager.session_scope() as session:
                curr_rev = (await get_current_state(session, task_id)).revision
            w = MockWorker(role, transport)
            await w.submit_response(task_id, event, rev)
            await asyncio.sleep(0.5)
            with db_manager.session_scope() as session:
                new_rev = (await get_current_state(session, task_id)).revision
            if new_rev == curr_rev:
                logger.info(f"N-Test {label}: ✅ REJECTED")
                return True
            logger.error(f"N-Test {label}: ❌ FAILED (State changed to {new_rev})")
            return False

        # N1: Stale Loop (Rev 0)
        await assert_rejected(TaskEvent.CODE_SUBMITTED, AssignedRole.CODER, 0, "N1-StaleLoop")
        # N2: Role Leak (CODER tries to approve)
        await assert_rejected(TaskEvent.REVIEW_APPROVED, AssignedRole.CODER, 3, "N2-RoleLeak")
        # N3: Phase Jump (REVIEWER tries to approve in CODING)
        await assert_rejected(TaskEvent.REVIEW_APPROVED, AssignedRole.REVIEWER, 3, "N3-PhaseJump")
        # N4: Double Fail (REVIEWER tries to fail in CODING)
        await assert_rejected(TaskEvent.REVIEW_FAILURE, AssignedRole.REVIEWER, 3, "N4-DoubleFail")
        # N6: Old-Reviewer Interference (Sends FAIL with Rev 2 while at Rev 3)
        await assert_rejected(TaskEvent.REVIEW_FAILURE, AssignedRole.REVIEWER, 2, "N6-OldReviewer")

        # --- HAPPY PATH: CYCLE 2 (The Success) ---
        logger.info("Executing Cycle 2: CODING -> VERIFYING -> REVIEWING -> COMPLETE")
        await coder.submit_response(task_id, TaskEvent.CODE_SUBMITTED, 3)
        await wait_for_state(4)
        await system.submit_response(task_id, TaskEvent.VERIFY_SUCCESS, 4)
        await wait_for_state(5)
        await reviewer.submit_response(task_id, TaskEvent.REVIEW_APPROVED, 5)
        state = await wait_for_state(6)
        logger.info(f"Cycle 2 Complete. Final State: {state}")

        # --- GHOST VERIFY TEST ---
        # N5: Ghost Verify from Cycle 1 (Rev 2) while at Rev 6
        await assert_rejected(TaskEvent.VERIFY_SUCCESS, AssignedRole.SYSTEM, 2, "N5-GhostVerify")

        # FINAL VERIFICATION
        with db_manager.session_scope() as session:
            final_state = await get_current_state(session, task_id)
            logs = session.query(TaskTransitionLog).filter(TaskTransitionLog.task_id == task_id).all()
            
            logger.info("\n--- FINAL TRANSITION LOG DUMP ---")
            rev_seq = []
            for l in logs:
                rev_seq.append(f"{l.previous_revision}->{l.new_revision}")
                logger.info(f"Rev {l.previous_revision}->{l.new_revision} | {l.from_phase} --({l.event})--> {l.to_phase} | Role: {l.sender_role} | Msg: {l.message_id}")
            logger.info(f"Revision Sequence: {' -> '.join(rev_seq)}")
            logger.info("--------------------------------\n")

        logger.info(f"Final State Snapshot: {final_state}")
        
        assert final_state.phase == ExecutionPhase.COMPLETE
        assert final_state.revision == 6
        assert final_state.transitions == 6
        assert final_state.role is None, f"Expected role None in COMPLETE, got {final_state.role}"
        
        logger.info("✅ PHASE 2C REGRESSION & CYCLICITY VERIFIED")

    finally:
        orchestrator_task.cancel()
        await transport.close()

if __name__ == "__main__":
    asyncio.run(run_regression_test())
