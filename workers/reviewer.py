import logging
import json
import time
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field, ValidationError
from engine.providers.base import BaseLLMProvider
from engine.models import Message, MessageHeader, MessageType, WorkerResponse
from engine.exceptions import WorkerExecutionError
from engine.prompt_loader import get_prompt_loader

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("firma.audit")


class ReviewerLLMOutput(BaseModel):
    decision: str = Field(description="REVIEW_APPROVED or REVIEW_FAILURE")
    issues: List[str] = Field(default_factory=list, description="Max 5 bullet issues")
    logs: Optional[str] = None
    thinking: Optional[str] = None


class ReviewerWorker:
    """
    ReviewerWorker: A strict adapter that reviews CODER output against acceptance criteria.
    
    Rules:
    1. Pure IO: No DB access, no filesystem access (except reading task spec).
    2. No Auto-Fix: Invalid JSON or Schema violations result in TASK_FAILED.
    3. No Retries: The worker does not retry; the Engine decides.
    4. One-Pass: Decide in ONE pass. No iteration.
    """

    def __init__(self, provider: BaseLLMProvider, model_name: str, dummy_mode: bool = False):
        self.provider = provider
        self.model_name = model_name
        self.dummy_mode = dummy_mode

    async def handle_assignment(self, project_id: str, plan_id: str, task_id: str, task_definition: Dict[str, Any], global_goal: str = "") -> Message:
        """
        Processes a review assignment and generates REVIEW_APPROVED or REVIEW_FAILURE.
        Enforces the strict Guardian Contract: no file modifications, one-pass decision.
        """
        logger.info(f"[Worker] RECEIVED REVIEW ASSIGNMENT: task={task_id}")
        
        if self.dummy_mode:
            logger.info(f"[DUMMY MODE] Generating Dummy Review for task {task_id}")
            # Dummy review: always approve
            dummy_response = ReviewerLLMOutput(
                decision="REVIEW_APPROVED",
                issues=[],
                logs="Dummy review: all acceptance criteria met."
            )
            return Message(
                type=MessageType.WORKER_RESPONSE,
                header=MessageHeader(
                    task_id=task_id,
                    sender_role="REVIEWER",
                    event="REVIEW_APPROVED"
                ),
                payload=dummy_response.model_dump()
            )
        
        # Load prompts from PromptLoader
        system_prompt = get_prompt_loader().load('reviewer', 'system')
        
        # Build user prompt from task definition
        # For reviewer, we need the CODER's artifacts to review
        review_artifacts = task_definition.get('review_artifacts', {})
        acceptance_criteria = task_definition.get('acceptance_criteria', [])
        
        user_prompt_parts = [
            f"Project ID: {project_id}",
            f"Task ID: {task_id}",
            "",
            "## Your Task (AUTHORITATIVE)",
            "You are a REVIEWER. Do NOT edit files. Do NOT iterate. Do NOT explore. ",
            "Allowed tools: ONLY `read` and `write`.",
            "- Use `read` ONLY for `.pi/messenger/crew/tasks/<TASK_ID>.md`.",
            "- Use `write` ONLY for the worker response file specified below.",
            "- VERBOTEN: `edit`, `bash`, `glob`, `grep`, further reads, further writes.",
            "",
            "Decide in ONE PASS whether the CODER implementation meets ALL acceptance criteria below. ",
            "Output must be either `REVIEW_APPROVED` or `REVIEW_FAILURE` plus max 5 bullet issues. ",
            "First action: write the worker response file. Then stop immediately.",
            "",
            "If you cannot decide within one pass, choose REVIEW_FAILURE with reason 'unclear'.",
            "",
            "## Code to Review (CODER output)",
        ]
        
        if review_artifacts:
            for fname, content in review_artifacts.items():
                user_prompt_parts.append(f"### `{fname}`")
                user_prompt_parts.append(f"```")
                user_prompt_parts.append(content)
                user_prompt_parts.append(f"```")
                user_prompt_parts.append("")
        else:
            user_prompt_parts.append("_(no artifacts found — reject as REVIEW_FAILURE)_")
            user_prompt_parts.append("")
        
        if acceptance_criteria:
            user_prompt_parts.append("## Acceptance Criteria (MUST PASS)")
            for criterion in acceptance_criteria:
                user_prompt_parts.append(f"- `{criterion}`")
            user_prompt_parts.append("")
        
        user_prompt = "\n".join(user_prompt_parts)
        
        logger.info(f"[Worker] ABOUT TO CALL PROVIDER: task={task_id} model={self.model_name}")
        start_time = time.time()
        
        try:
            if hasattr(self.provider, "set_role_context"):
                self.provider.set_role_context(
                    role="REVIEWER",
                    task_id=task_id,
                    task_definition=task_definition
                )
            
            # 1. Generate JSON via Provider
            raw_output = await self.provider.generate_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema=ReviewerLLMOutput.model_json_schema()
            )
            
            # 2. Validate with Pydantic
            try:
                validated_output = ReviewerLLMOutput(**raw_output)
            except ValidationError as e:
                logger.error(f"[Worker] Schema validation failed for task {task_id}: {e}")
                error_response = ReviewerLLMOutput(
                    decision="REVIEW_FAILURE",
                    issues=[f"Schema validation error: {str(e)}"],
                    logs="Worker failed to produce valid JSON."
                )
                return Message(
                    type=MessageType.WORKER_RESPONSE,
                    header=MessageHeader(
                        task_id=task_id,
                        sender_role="REVIEWER",
                        event="REVIEW_FAILURE"
                    ),
                    payload=error_response.model_dump()
                )
            
            # 3. Determine event based on decision
            event = "REVIEW_APPROVED" if validated_output.decision == "REVIEW_APPROVED" else "REVIEW_FAILURE"
            
            # 4. Build WorkerResponse
            response = WorkerResponse(
                protocol_version="1.0",
                message_id=f"{task_id}-review-{int(time.time())}",
                task_id=task_id,
                run_id=task_definition.get("run_id", ""),
                state_revision=task_definition.get("state_revision", 0),
                event=event,
                sender_role="REVIEWER",
                artifacts=[],  # Reviewer does not produce artifacts
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                logs=validated_output.logs or f"Review completed: {event}",
                thinking=validated_output.thinking
            )
            
            duration = time.time() - start_time
            logger.info(f"[Worker] REVIEW COMPLETED: task={task_id} decision={event} duration={duration:.2f}s")
            audit_logger.info(f"REVIEWER {task_id} {event} issues={len(validated_output.issues)} duration={duration:.2f}s")
            
            return Message(
                type=MessageType.WORKER_RESPONSE,
                header=MessageHeader(
                    task_id=task_id,
                    sender_role="REVIEWER",
                    event=event
                ),
                payload=response.model_dump()
            )
            
        except Exception as e:
            logger.error(f"[Worker] REVIEW FAILED for task {task_id}: {e}")
            error_response = WorkerResponse(
                protocol_version="1.0",
                message_id=f"{task_id}-review-error-{int(time.time())}",
                task_id=task_id,
                run_id=task_definition.get("run_id", ""),
                state_revision=task_definition.get("state_revision", 0),
                event="REVIEW_FAILURE",
                sender_role="REVIEWER",
                artifacts=[],
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                logs=f"Review failed with exception: {str(e)}"
            )
            return Message(
                type=MessageType.WORKER_RESPONSE,
                header=MessageHeader(
                    task_id=task_id,
                    sender_role="REVIEWER",
                    event="REVIEW_FAILURE"
                ),
                payload=error_response.model_dump()
            )
