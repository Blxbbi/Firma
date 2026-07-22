from typing import Optional, Callable, List, Dict, Any
import time
from .models import Message, GuardResult, MessageType, PlanDraftSchema
from .repository import MessageRepository
from engine.services.telemetry import telemetry

class MessageGuards:
    """
    Deterministic validation logic connected to the real Repository for Task messages.
    """
    @staticmethod
    def guard_idempotency(repo: MessageRepository, message: Message) -> GuardResult:
        t0 = time.perf_counter_ns()
        if repo.is_message_processed(message.header.message_id):
            telemetry.increment("illegal_transition_count")
            res = GuardResult(
                passed=False, 
                error_code="ERR_DUPLICATE_MESSAGE", 
                reason=f"Nachricht {message.header.message_id} wurde bereits verarbeitet."
            )
        else:
            res = GuardResult(passed=True)
        
        telemetry.observe("guard_eval_latency_ns", time.perf_counter_ns() - t0)
        return res

    @staticmethod
    def guard_state_consistency(repo: MessageRepository, task_id: str, event: str) -> GuardResult:
        t0 = time.perf_counter_ns()
        task = repo.get_task(task_id)
        if not task:
            res = GuardResult(passed=False, error_code="ERR_TASK_NOT_FOUND", reason="Task nicht gefunden.")
        else:
            current_state = task.state
            transitions = MessageGuards.VALID_TRANSITIONS.get(current_state, {})
            
            if event not in transitions:
                telemetry.increment("illegal_transition_count")
                res = GuardResult(
                    passed=False, 
                    error_code="ERR_INVALID_TRANSITION", 
                    reason=f"Übergang von '{current_state}' via '{event}' ist nicht erlaubt."
                )
            else:
                res = GuardResult(passed=True)
        
        telemetry.observe("guard_eval_latency_ns", time.perf_counter_ns() - t0)
        return res

class PlanGuards:
    """
    Deterministic validation logic for Plan messages.
    """

    @staticmethod
    def guard_idempotency(repo: MessageRepository, message: Message) -> GuardResult:
        # For plans, idempotency might be checked against plan_id if provided, 
        # or message_id for the submission event itself.
        return MessageGuards.guard_idempotency(repo, message)

    @staticmethod
    def guard_plan_schema(repo: MessageRepository, message: Message) -> GuardResult:
        try:
            # We expect the payload to be the plan draft
            PlanDraftSchema.model_validate(message.payload)
            return GuardResult(passed=True)
        except Exception as e:
            return GuardResult(
                passed=False,
                error_code="ERR_INVALID_PLAN_SCHEMA",
                reason=f"Plan Schema ungültig: {str(e)}"
            )

    @staticmethod
    def guard_plan_uniqueness(repo: MessageRepository, message: Message) -> GuardResult:
        payload = message.payload
        plan_name = payload.get("plan_name")
        
        if not plan_name:
            return GuardResult(passed=False, error_code="ERR_MISSING_PLAN_NAME", reason="Plan Name fehlt im Payload.")

        # Check if plan with this name already exists
        existing_plan = repo.get_plan_by_name(plan_name)
        if existing_plan:
            return GuardResult(
                passed=False,
                error_code="ERR_PLAN_ALREADY_EXISTS",
                reason=f"Ein Plan mit dem Namen '{plan_name}' existiert bereits."
            )
        
        return GuardResult(passed=True)

# Registry to map MessageTypes to their respective Guard chains
# This allows the workflow to dynamically pick the right guards.
GUARD_REGISTRY: Dict[MessageType, List[Callable[[MessageRepository, Message], GuardResult]]] = {
    MessageType.TASK_ACK: [MessageGuards.guard_idempotency],
    MessageType.WORKER_RESPONSE: [MessageGuards.guard_idempotency],
    MessageType.VALIDATION_RESULT: [MessageGuards.guard_idempotency],
    
    # Special case: Planner drafts are still worker responses but need structural checks
    # Note: We consolidate these into WORKER_RESPONSE but can add specific guards
    # if the Guardian checks the 'event' inside the payload.
}
