import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Tuple, List, Dict, Any

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
logger = logging.getLogger("Phase2B-FullPipeline")

class PipelineState(BaseModel):
    phase: ExecutionPhase
    role: AssignedRole
    revision: int
    transitions: int

async def get_current_state(session, task_id):
    repo = MessageRepository()
    task = repo.get_task_by_id(session, task_id)
    from engine.models import TaskEventLog
    transitions = session.query(TaskEventLog).filter(TaskEventLog.task_id == task_id).count()
    # Note: This count might include rejected events if they were logged, 
    # but TaskTransitionLog only tracks successful ones.
    trans_count = session.query(TaskTransitionLog).filter(TaskTransitionLog.task_id == task_id).count()
    return PipelineState(
        phase=ExecutionPhase(task.execution_phase),
        role=AssignedRole(task.assigned_role),
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
        # Use the helper to send a WORKER_RESPONSE envelope
        await self.transport.publish_response(
            role=self.role.value,
            payload=payload
        )
        logger.info(f"[Worker {self.role}] Sent {event} for {task_id} (Rev {revision})")

async def run_full_pipeline_test():
    """
    Phase 2B.2 Full Pipeline Integration Test.
    CODING -> VERIFYING -> REVIEWING -> COMPLETE
    """
    logger.info("--- STARTING PHASE 2B.2 FULL PIPELINE INTEGRATION TEST ---")
    
    # Configuration
    task_id = "T-FULL-01"
    db_url = "sqlite:///mesh_full_pipeline.db"
    db_manager = DatabaseManager(db_url)
    Base.metadata.drop_all(db_manager.engine)
    Base.metadata.create_all(db_manager.engine)
    
    # 1. Infrastructure Setup
    # Using PiMessengerTransport (requires NATS running)
    transport = PiMessengerTransport(nats_url="nats://localhost:4222")
    await transport.connect()
    
    # Mock dependencies for Orchestrator
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
    
    # Create Workers
    coder = MockWorker(AssignedRole.CODER, transport)
    reviewer = MockWorker(AssignedRole.REVIEWER, transport)
    # SYSTEM is internal to the orchestrator/guardian logic in this setup, 
    # but the orchestrator will handle the 'SYSTEM' role transition.
    
    # 2. Initial State Setup
    with db_manager.session_scope() as session:
        project = Project(id="P-FULL", name="Full Pipeline Project")
        session.add(project)
        session.flush()
        plan = Plan(id="PL-FULL", project_id=project.id, version=1, name="Full Plan", status="IN_PROGRESS")
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

    # Start Orchestrator in background
    orchestrator_task = asyncio.create_task(orchestrator.run_forever())
    await asyncio.sleep(1) # Allow NATS connection

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
        # --- HAPPY PATH ---
        
        # T1: Coder submits
        await coder.submit_response(task_id, TaskEvent.CODE_SUBMITTED, 0)
        state = await wait_for_state(1)
        logger.info(f"T1 Success: {state}")

        # T2: System verifies (The Orchestrator handles SYSTEM role transitions usually, 
        # but here we simulate a SYSTEM response through the transport to test the Guardian)
        system_worker = MockWorker(AssignedRole.SYSTEM, transport)
        await system_worker.submit_response(task_id, TaskEvent.VERIFY_SUCCESS, 1)
        state = await wait_for_state(2)
        logger.info(f"T2 Success: {state}")

        # T3: Reviewer approves
        await reviewer.submit_response(task_id, TaskEvent.REVIEW_APPROVED, 2)
        state = await wait_for_state(3)
        logger.info(f"T3 Success: {state}")

        # --- NEGATIVE MATRIX ---
        
        # We track rejections by checking if revision stays the same after an event
        async def assert_rejected(event: TaskEvent, role: AssignedRole, rev: int, label: str):
            current_rev = (await get_current_state(db_manager.session_scope(), task_id)).revision # this is wrong usage of session_scope
            # Corrected:
            with db_manager.session_scope() as session:
                current_rev = (await get_current_state(session, task_id)).revision
            
            worker = MockWorker(role, transport)
            await worker.submit_response(task_id, event, rev)
            await asyncio.sleep(0.5)
            
            with db_manager.session_scope() as session:
                new_state = await get_current_state(session, task_id)
            
            if new_state.revision == current_rev:
                logger.info(f"N-Test {label}: ✅ REJECTED as expected")
                return True
            else:
                logger.error(f"N-Test {label}: ❌ FAILED (State changed!)")
                return False

        # Wrap session_scope for the helper
        async def helper_rejected(event: TaskEvent, role: AssignedRole, rev: int, label: str):
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
            return False

        # N1: REVIEW_APPROVED in CODING (not possible now as we are at Rev 3, but let's try a stale one)
        await helper_rejected(TaskEvent.REVIEW_APPROVED, AssignedRole.REVIEWER, 0, "N1 (Stale Rev)")
        
        # N2: VERIFY_SUCCESS in REVIEWING (T3 already happened)
        await helper_rejected(TaskEvent.VERIFY_SUCCESS, AssignedRole.SYSTEM, 3, "N2 (Wrong Phase)")

        # N3: REVIEW_APPROVED from SYSTEM
        await helper_rejected(TaskEvent.REVIEW_APPROVED, AssignedRole.SYSTEM, 3, "N3 (Wrong Role)")

        # N4: Double REVIEW_APPROVED
        await helper_rejected(TaskEvent.REVIEW_APPROVED, AssignedRole.REVIEWER, 3, "N4 (Double Transition)")

        # N5: Stale REVIEW_APPROVED
        await helper_rejected(TaskEvent.REVIEW_APPROVED, AssignedRole.REVIEWER, 2, "N5 (Stale Rev)")

        # N6: CODE_SUBMITTED in REVIEWING (though we are COMPLETE)
        await helper_rejected(TaskEvent.CODE_SUBMITTED, AssignedRole.CODER, 3, "N6 (Wrong Phase)")

        # --- STRESS TEST ---
        logger.info("Running Stress Test: Concurrent Illegal Events...")
        stress_events = [
            (TaskEvent.REVIEW_APPROVED, AssignedRole.REVIEWER, 1), # Stale
            (TaskEvent.CODE_SUBMITTED, AssignedRole.CODER, 3),    # Wrong Phase
            (TaskEvent.VERIFY_SUCCESS, AssignedRole.SYSTEM, 3),   # Wrong Phase
            (TaskEvent.REVIEW_APPROVED, AssignedRole.SYSTEM, 3),  # Wrong Role
            (TaskEvent.REVIEW_APPROVED, AssignedRole.REVIEWER, 2),# Stale
        ]
        for e, r, v in stress_events:
            w = MockWorker(r, transport)
            await w.submit_response(task_id, e, v)
        
        await asyncio.sleep(1)
        
        # FINAL VERIFICATION
        with db_manager.session_scope() as session:
            final_state = await get_current_state(session, task_id)
            
            # Transition Log Dump
            logs = session.query(TaskTransitionLog).filter(TaskTransitionLog.task_id == task_id).all()
            logger.info("\n--- FINAL TRANSITION LOG DUMP ---")
            for l in logs:
                logger.info(f"Rev {l.previous_revision}->{l.new_revision} | {l.from_phase} --({l.event})--> {l.to_phase} | Role: {l.sender_role} | Msg: {l.message_id}")
            logger.info("--------------------------------\n")

        logger.info(f"Final State Snapshot: {final_state}")
        
        assert final_state.phase == ExecutionPhase.COMPLETE
        assert final_state.revision == 3
        assert final_state.transitions == 3
        
        logger.info("✅ PHASE 2B.2 FULL PIPELINE COHERENCE VERIFIED")

    finally:
        orchestrator_task.cancel()
        await transport.close()

if __name__ == "__main__":
    asyncio.run(run_full_pipeline_test())
