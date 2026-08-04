import logging
from typing import Dict, Tuple, Optional, NamedTuple, Set
from engine.models import ExecutionPhase, AssignedRole, TaskEvent

logger = logging.getLogger(__name__)

class TransitionResult(NamedTuple):
    next_phase: ExecutionPhase
    next_role: Optional[AssignedRole]

class IllegalTransitionError(Exception):
    """Raised when a phase transition is not defined in the governance matrix."""
    def __init__(self, current_phase: ExecutionPhase, event: TaskEvent):
        self.current_phase = current_phase
        self.event = event
        super().__init__(f"Illegal transition: Phase {current_phase} cannot handle event {event}")

class GovernanceMatrix:
    """
    GovernanceMatrix: The formal FSM of the Firma Engine.
    
    Defines exactly how a task moves from one phase to another based on events.
    This is the 'Single Source of Truth' for runtime governance.
    """

    # (CurrentPhase, Event) -> (NextPhase, NextRole)
    _matrix: Dict[Tuple[ExecutionPhase, TaskEvent], TransitionResult] = {
        # Planning transitions
        (ExecutionPhase.PLANNING, TaskEvent.PLAN_SUBMITTED): TransitionResult(ExecutionPhase.CODING, AssignedRole.CODER),
        (ExecutionPhase.PLANNING, TaskEvent.PLAN_APPROVED): TransitionResult(ExecutionPhase.CODING, AssignedRole.CODER),
        (ExecutionPhase.PLANNING, TaskEvent.PLAN_REJECTED): TransitionResult(ExecutionPhase.PLANNING, AssignedRole.PLANNER),
        (ExecutionPhase.PLANNING, TaskEvent.WORKER_TIMEOUT): TransitionResult(ExecutionPhase.PLANNING, AssignedRole.PLANNER),
        (ExecutionPhase.PLANNING, TaskEvent.TASK_FAILED): TransitionResult(ExecutionPhase.PLANNING, AssignedRole.PLANNER),
        
        # Coding transitions
        (ExecutionPhase.CODING, TaskEvent.CODE_SUBMITTED): TransitionResult(ExecutionPhase.VERIFYING, AssignedRole.SYSTEM),
        (ExecutionPhase.CODING, TaskEvent.SUBMISSION_INVALID_SCHEMA): TransitionResult(ExecutionPhase.CODING, AssignedRole.CODER),
        (ExecutionPhase.CODING, TaskEvent.TASK_FAILED): TransitionResult(ExecutionPhase.CODING, AssignedRole.CODER),
        (ExecutionPhase.CODING, TaskEvent.WORKER_TIMEOUT): TransitionResult(ExecutionPhase.CODING, AssignedRole.CODER),
        
        # Verifying transitions
        (ExecutionPhase.VERIFYING, TaskEvent.VERIFY_SUCCESS): TransitionResult(ExecutionPhase.REVIEWING, AssignedRole.REVIEWER),
        (ExecutionPhase.VERIFYING, TaskEvent.VERIFY_FAILURE): TransitionResult(ExecutionPhase.CODING, AssignedRole.CODER),
        (ExecutionPhase.VERIFYING, TaskEvent.WORKER_TIMEOUT): TransitionResult(ExecutionPhase.VERIFYING, AssignedRole.SYSTEM),
        
        # Reviewing transitions
        (ExecutionPhase.REVIEWING, TaskEvent.REVIEW_APPROVED): TransitionResult(ExecutionPhase.COMPLETE, None),
        (ExecutionPhase.REVIEWING, TaskEvent.REVIEW_FAILURE): TransitionResult(ExecutionPhase.CODING, AssignedRole.CODER),
        (ExecutionPhase.REVIEWING, TaskEvent.WORKER_TIMEOUT): TransitionResult(ExecutionPhase.REVIEWING, AssignedRole.REVIEWER),
        
        # Global failure transitions
        (ExecutionPhase.RESEARCHING, TaskEvent.RESEARCH_COMPLETE): TransitionResult(ExecutionPhase.COMPLETE, None),
        (ExecutionPhase.RESEARCHING, TaskEvent.TASK_FAILED): TransitionResult(ExecutionPhase.RESEARCHING, AssignedRole.RESEARCHER),
        (ExecutionPhase.RESEARCHING, TaskEvent.WORKER_TIMEOUT): TransitionResult(ExecutionPhase.RESEARCHING, AssignedRole.RESEARCHER),
    }

    # Event -> Allowed Roles
    _role_auth: Dict[TaskEvent, Set[AssignedRole]] = {
        TaskEvent.PLAN_SUBMITTED: {AssignedRole.PLANNER},
        TaskEvent.PLAN_APPROVED: {AssignedRole.PLANNER},
        TaskEvent.PLAN_REJECTED: {AssignedRole.PLANNER},
        TaskEvent.RESEARCH_COMPLETE: {AssignedRole.RESEARCHER},
        TaskEvent.CODE_SUBMITTED: {AssignedRole.CODER},
        TaskEvent.SUBMISSION_INVALID_SCHEMA: {AssignedRole.SYSTEM, AssignedRole.CODER},
        TaskEvent.VERIFY_SUCCESS: {AssignedRole.SYSTEM},
        TaskEvent.VERIFY_FAILURE: {AssignedRole.SYSTEM},
        TaskEvent.REVIEW_APPROVED: {AssignedRole.REVIEWER},
        TaskEvent.REVIEW_FAILURE: {AssignedRole.REVIEWER},
        TaskEvent.TASK_FAILED: {AssignedRole.PLANNER, AssignedRole.RESEARCHER, AssignedRole.CODER, AssignedRole.REVIEWER},
        TaskEvent.WORKER_TIMEOUT: {AssignedRole.SYSTEM},
    }

    # Phase -> Allowed Events
    _phase_auth: Dict[ExecutionPhase, Set[TaskEvent]] = {
        ExecutionPhase.PLANNING: {TaskEvent.PLAN_SUBMITTED, TaskEvent.PLAN_APPROVED, TaskEvent.PLAN_REJECTED, TaskEvent.WORKER_TIMEOUT, TaskEvent.TASK_FAILED},
        ExecutionPhase.RESEARCHING: {TaskEvent.RESEARCH_COMPLETE, TaskEvent.TASK_FAILED, TaskEvent.WORKER_TIMEOUT},
        ExecutionPhase.CODING: {TaskEvent.CODE_SUBMITTED, TaskEvent.SUBMISSION_INVALID_SCHEMA, TaskEvent.TASK_FAILED, TaskEvent.WORKER_TIMEOUT},
        ExecutionPhase.VERIFYING: {TaskEvent.VERIFY_SUCCESS, TaskEvent.VERIFY_FAILURE, TaskEvent.WORKER_TIMEOUT},
        ExecutionPhase.REVIEWING: {TaskEvent.REVIEW_APPROVED, TaskEvent.REVIEW_FAILURE, TaskEvent.WORKER_TIMEOUT},
    }

    @classmethod
    def transition(cls, current_phase: ExecutionPhase, event: TaskEvent) -> TransitionResult:
        """
        Deterministically calculates the next state based on the current phase and event.
        """
        try:
            result = cls._matrix[(current_phase, event)]
            logger.info(f"🚀 [STAGE TRANSITION] {current_phase} --({event})--> {result.next_phase} (Role: {result.next_role})")
            return result
        except KeyError:
            logger.error(f"[Governance] Illegal transition attempt: {current_phase} with event {event}")
            raise IllegalTransitionError(current_phase, event)

    @classmethod
    def authorize_event(cls, phase: ExecutionPhase, role: AssignedRole, event: TaskEvent) -> bool:
        """
        Validates if a specific role is allowed to trigger a specific event in a specific phase.
        """
        # Check: Is the event allowed in this phase?
        if event not in cls._phase_auth.get(phase, set()):
            logger.warning(f"[Governance] Event {event} is not allowed in phase {phase}")
            return False
        
        # Check: Is the role authorized to trigger this event?
        if role not in cls._role_auth.get(event, set()):
            logger.warning(f"[Governance] Role {role} is not authorized to trigger event {event}")
            return False
        
        return True

    @classmethod
    def get_all_transitions(cls):
        """Returns the full matrix for audit and testing."""
        return cls._matrix
