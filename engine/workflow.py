from typing import Tuple
import logging
import json
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy.orm import Session
from engine.models import Message, MessageType, Task, Plan, Project, PlanDraftSchema
from sqlalchemy import select
from engine.repository import MessageRepository
from engine.services.artifact_store import ArtifactStore
from engine.services.verification_service import VerificationService
from engine.services.execution import ExecutionService
from engine.services.spec_gate import SpecGate
from engine.services.plan_instantiator import PlanInstantiationService
from engine.governance import GovernanceMatrix, IllegalTransitionError
from engine.services.guardian import GuardianPipeline
from engine.models import ExecutionPhase, TaskEvent, WorkerResponse
from engine.models import ExecutionPhase, TaskEvent

logger = logging.getLogger(__name__)

def process_plan_draft(session: Session, msg: Message, project_id: str, artifact_store_root: str = None):
    """
    Processes a submitted Plan Draft.
    Integrates the Spec-Gate to ensure only executable plans are instantiated.
    """
    repo = MessageRepository(artifact_store_root=artifact_store_root)
    
    # 1. Project Context Validation
    project = repo.get_project(session, project_id)
    if not project:
        logger.error(f"Plan Workflow rejected: Project {project_id} not found.")
        return False

    # 2. Idempotency Check
    if repo.is_message_processed(session, msg.header.message_id):
        logger.info(f"Plan message {msg.header.message_id} already processed. Skipping.")
        return True

    # 3. Spec-Gate Validation
    # The payload for a plan draft is expected to be a JSON string or a dict
    payload = msg.payload
    plan_draft_data = payload.get("plan_draft")
    
    if not plan_draft_data:
        logger.error(f"Plan Workflow rejected: No plan_draft found in payload.")
        return False

    # Convert dict to JSON string for SpecGate (which expects a raw string from the LLM)
    plan_str = json.dumps(plan_draft_data) if isinstance(plan_draft_data, dict) else plan_draft_data
    
    logger.info(f"Passing plan draft to Spec-Gate for project {project_id}...")
    validation_result = SpecGate.validate(plan_str)
    
    if not validation_result.approved:
        logger.warning(f"Spec-Gate REJECTED plan for project {project_id}:\n- " + "\n- ".join(validation_result.errors))
        
        # Mark as processed but log the rejection reason
        repo.mark_message_processed(
            session, 
            msg.header.message_id, 
            "DRAFT", # No plan_id yet
            "PLANNER", 
            msg.header.sender, 
            msg.header.recipient, 
            msg.header.message_type.value,
            error_reason="SPEC_GATE_REJECTED: " + "; ".join(validation_result.errors)
        )
        return False

    # 4. Plan Instantiation
    # The SpecGate already parsed and validated the plan into a PlanSpec object
    try:
        # Convert PlanSpec back to PlanDraftSchema for the InstantiationService
        # In a real system, we'd probably unify these models.
        draft_schema = PlanDraftSchema(**validation_result.parsed_plan.model_dump())
        
        instantiator = PlanInstantiationService(session)
        new_plan = instantiator.instantiate_plan(draft_schema)
        
        # Set as active plan for the project
        project.active_plan_id = new_plan.id
        
        # Mark message as processed
        repo.mark_message_processed(
            session, 
            msg.header.message_id, 
            new_plan.id, 
            "PLANNER", 
            msg.header.sender, 
            msg.header.recipient, 
            msg.header.message_type.value
        )
        
        logger.info(f"Plan {new_plan.id} APPROVED by Spec-Gate and instantiated for project {project_id}.")
        return True

    except Exception as e:
        logger.exception(f"Critical failure during plan instantiation for project {project_id}: {str(e)}")
        return False

def process_task_message_detailed(session: Session, msg: Message, task_id: str, msg_type: MessageType, project_id: str, artifact_store_root: str = None) -> Tuple[bool, str]:
    """
    Returns (success, reason) where reason can be 'SUCCESS', 'ALREADY_PROCESSED', or the error message.
    """
    repo = MessageRepository(artifact_store_root=artifact_store_root)
    
    project = repo.get_project(session, project_id)
    if not project:
        return False, "Project not found"

    artifact_store = ArtifactStore()
    guardian = GuardianPipeline(artifact_store)
    
    success, reason = guardian.process_response(session, msg.payload)
    
    if not success:
        if reason == "ALREADY_PROCESSED":
            return True, "ALREADY_PROCESSED"
        
        repo.mark_message_processed(
            session, 
            msg.header.message_id, 
            "UNKNOWN", 
            "UNKNOWN", 
            msg.header.sender, 
            msg.header.recipient, 
            msg_type.value,
            error_reason=reason
        )
        return False, reason

    return True, reason

async def process_task_message(session: Session, msg: Message, task_id: str, msg_type: MessageType, project_id: str, artifact_store_root: str = None):
    """
    The primary entry point for processing worker responses.
    Now routed through the Guardian Pipeline for strict validation.
    """
    repo = MessageRepository(artifact_store_root=artifact_store_root)
    
    # 1. Basic Context Validation
    project = await repo.get_project(session, project_id)
    if not project:
        logger.error(f"Workflow rejected: Project {project_id} not found.")
        return False

    # 2. Route to Guardian Pipeline
    artifact_store = ArtifactStore()
    guardian = GuardianPipeline(artifact_store)
    
    # The msg.payload is now treated as a WorkerResponse
    success, error_msg = await guardian.process_response(session, msg.payload)
    
    if not success:
        if error_msg == "ALREADY_PROCESSED":
            logger.info(f"Message {msg.header.message_id} already processed. Skipping.")
            return True
        
        logger.warning(f"Guardian rejected response for task {task_id}: {error_msg}")
        
        # Mark as processed but log the rejection reason to prevent infinite retry loops
        await repo.mark_message_processed(
            session, 
            msg.header.message_id, 
            "UNKNOWN", 
            "UNKNOWN", 
            msg.header.sender, 
            msg.header.recipient, 
            msg_type.value,
            error_reason=error_msg
        )
        return False

    # 3. Post-Processing (e.g. Dependency Resolution)
    # If the task just became COMPLETE, we unblock others.
    result = await session.execute(select(Task).filter(Task.id == task_id))
    task = result.scalars().first()
    
    if task and task.execution_phase == ExecutionPhase.COMPLETE:
        result_plan = await session.execute(select(Plan).filter(Plan.id == task.plan_id))
        active_plan = result_plan.scalars().first()
        
        result_blocked = await session.execute(select(Task).filter(
            Task.plan_id == active_plan.id,
            Task.state == "BLOCKED"
        ))
        blocked_tasks = result_blocked.scalars().all()
        
        for bt in blocked_tasks:
            deps = bt.dependencies or []
            all_verified = True
            for dep_id in deps:
                result_dep = await session.execute(select(Task).filter(Task.id == dep_id, Task.plan_id == active_plan.id))
                dep_task = result_dep.scalars().first()
                if not dep_task or dep_task.state != "VERIFIED":
                    all_verified = False
                    break
            
            if all_verified:
                logger.info(f"Task {bt.id} unblocked and moved to READY.")
                bt.state = "READY"
                bt.updated_at = datetime.now(timezone.utc)

    return True

async def execute_submitted_task(session: Session, sandbox, task_id: str, project_id: str):
    """
    The coordinator for the SUBMITTED -> VERIFIED flow.
    Now strictly bound to project_id.
    """
    repo = MessageRepository()
    
    # 1. Context Validation
    project = repo.get_project(session, project_id)
    if not project or not project.active_plan_id:
        logger.error(f"Execution rejected: Project {project_id} has no active plan.")
        return False
    
    active_plan = repo.get_active_plan(session, project_id)
    task = repo.get_task(session, project_id, active_plan.id, task_id)
    
    if not task or task.state != "SUBMITTED":
        logger.error(f"Execution rejected: Task {task_id} is not in SUBMITTED state.")
        return False

    # 2. Execution Phase
    exec_service = ExecutionService(sandbox)
    result = await exec_service.execute(session, project_id, active_plan.id, active_plan.version, task_id)
    
    # 3. Verification Phase
    verify_service = VerificationService(sandbox)
    verification_result = await verify_service.verify(task, result, Path(result.cwd))
    
    # 4. Governance Transition
    try:
        current_phase = ExecutionPhase(task.execution_phase)
        event = TaskEvent.VERIFY_SUCCESS if verification_result.passed else TaskEvent.VERIFY_FAILURE
        
        transition_res = GovernanceMatrix.transition(current_phase, event)
        
        # Update Governance State
        task.execution_phase = transition_res.next_phase.value
        if transition_res.next_role:
            task.assigned_role = transition_res.next_role.value
        
        task.state_revision += 1
        
        # Map Phase to Orchestrator State
        if transition_res.next_phase == ExecutionPhase.COMPLETE:
            task.state = "VERIFIED"
            logger.info(f"Task {task_id} successfully VERIFIED and COMPLETE for project {project_id}.")
            
            # --- Dependency Resolution ---
            from engine.models import Task as TaskModel
            blocked_tasks = session.query(TaskModel).filter(
                TaskModel.plan_id == active_plan.id,
                TaskModel.state == "BLOCKED"
            ).all()
            
            for bt in blocked_tasks:
                deps = bt.dependencies or []
                all_verified = True
                for dep_id in deps:
                    dep_task = session.query(TaskModel).filter(TaskModel.id == dep_id, TaskModel.plan_id == active_plan.id).first()
                    if not dep_task or dep_task.state != "VERIFIED":
                        all_verified = False
                        break
                
                if all_verified:
                    logger.info(f"Task {bt.id} unblocked and moved to READY.")
                    repo.update_task_state(session, project_id, bt.id, "READY")
        else:
            # If not COMPLETE, it's either back to CODING (retry) or moving to REVIEWING
            task.state = "READY"
            logger.info(f"Task {task_id} transitioned to {task.execution_phase} (State: READY) for project {project_id}.")

    except IllegalTransitionError as e:
        logger.error(f"Critical Governance Failure for task {task_id}: {str(e)}")
        task.state = "FAILED" # Kill the task if the FSM is violated
    
    task.updated_at = datetime.now(timezone.utc)
    return verification_result.passed
