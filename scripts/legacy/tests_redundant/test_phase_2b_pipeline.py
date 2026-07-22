import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Tuple

from engine.db import DatabaseManager
from engine.models import Base, Task, ExecutionPhase, AssignedRole, TaskEvent
from engine.repository import MessageRepository
from engine.services.guardian import GuardianPipeline
from engine.services.artifact_store import ArtifactStore
from pydantic import BaseModel

# Logging Configuration
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger("Phase2B-Pipeline")

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
    return PipelineState(
        phase=ExecutionPhase(task.execution_phase),
        role=AssignedRole(task.assigned_role),
        revision=task.state_revision,
        transitions=transitions
    )

async def run_pipeline_test():
    """
    Phase 2B.1 Pipeline Test: CODING -> VERIFYING -> REVIEWING (as per current Matrix)
    Tests both Happy Path and Negative Transitions.
    """
    logger.info("--- STARTING PHASE 2B.1 PIPELINE COHERENCE TEST ---")
    task_id = "T-PIPE-01"
    db_manager = DatabaseManager("sqlite:///mesh_pipeline.db")
    Base.metadata.create_all(db_manager.engine)
    
    # 1. INITIAL STATE SETUP
    with db_manager.session_scope() as session:
        from engine.models import Project, Plan
        project = Project(id="P-PIPE", name="Pipeline Project")
        session.add(project)
        session.flush()
        plan = Plan(id="PL-PIPE", project_id=project.id, version=1, name="Pipe Plan", status="IN_PROGRESS")
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

    guardian = GuardianPipeline(ArtifactStore())

    async def attempt_transition(event: TaskEvent, role: AssignedRole, rev: int, label: str):
        logger.info(f"Testing {label}: Event={event}, Role={role}, Rev={rev}")
        with db_manager.session_scope() as session:
            state_before = await get_current_state(session, task_id)
            
            # Mock payload for Guardian
            payload = {
                "protocol_version": "1.0",
                "message_id": f"msg-{uuid.uuid4().hex[:6]}",
                "task_id": task_id,
                "state_revision": rev,
                "event": event,
                "sender_role": role,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "artifacts": {}
            }
            
            success, reason = guardian.process_response(session, payload)
            state_after = await get_current_state(session, task_id)
            
            logger.info(f"Result: {'✅ SUCCESS' if success else '❌ REJECTED'} ({reason})")
            logger.info(f"State: {state_before} -> {state_after}")
            return success, state_after

    import uuid

    # --- TEST SEQUENCE ---
    
    # 1. Initial Assertion
    with db_manager.session_scope() as session:
        init_state = await get_current_state(session, task_id)
        logger.info(f"Initial State: {init_state}")
        assert init_state.phase == ExecutionPhase.CODING
        assert init_state.role == AssignedRole.CODER
        assert init_state.revision == 0

    # 2. N1: VERIFY_SUCCESS in CODING (Illegal Phase)
    success, state = await attempt_transition(TaskEvent.VERIFY_SUCCESS, AssignedRole.SYSTEM, 0, "N1: Early Verify")
    assert not success
    assert state.revision == 0

    # 3. T1: CODE_SUBMITTED (Happy Path)
    success, state = await attempt_transition(TaskEvent.CODE_SUBMITTED, AssignedRole.CODER, 0, "T1: Submit Code")
    assert success
    assert state.phase == ExecutionPhase.VERIFYING
    assert state.role == AssignedRole.SYSTEM
    assert state.revision == 1

    # 4. N2: CODE_SUBMITTED in VERIFYING (Illegal Phase)
    success, state = await attempt_transition(TaskEvent.CODE_SUBMITTED, AssignedRole.CODER, 1, "N2: Duplicate Submit")
    assert not success
    assert state.revision == 1

    # 5. N3: VERIFY_SUCCESS from CODER (Illegal Role)
    success, state = await attempt_transition(TaskEvent.VERIFY_SUCCESS, AssignedRole.CODER, 1, "N3: Wrong Role Verify")
    assert not success
    assert state.revision == 1

    # 6. T2: VERIFY_SUCCESS (Happy Path)
    # Note: As per current GovernanceMatrix, VERIFYING -> REVIEWING
    success, state = await attempt_transition(TaskEvent.VERIFY_SUCCESS, AssignedRole.SYSTEM, 1, "T2: Verify Success")
    assert success
    assert state.phase == ExecutionPhase.REVIEWING
    assert state.role == AssignedRole.REVIEWER
    assert state.revision == 2

    # 7. N4: Double VERIFY_SUCCESS (Illegal Transition)
    success, state = await attempt_transition(TaskEvent.VERIFY_SUCCESS, AssignedRole.SYSTEM, 2, "N4: Double Verify")
    assert not success
    assert state.revision == 2

    # 8. N5: Stale Revision Submission
    success, state = await attempt_transition(TaskEvent.CODE_SUBMITTED, AssignedRole.CODER, 0, "N5: Stale Rev Submit")
    assert not success
    assert state.revision == 2

    logger.info("✅ PHASE 2B.1 PIPELINE COHERENCE VERIFIED: Sequencing and Idempotency are intact.")

if __name__ == "__main__":
    asyncio.run(run_pipeline_test())
