import logging
import json
import time
from datetime import datetime
from typing import Dict, Any, Tuple, Optional
from pydantic import ValidationError
from engine.providers.base import BaseLLMProvider
from engine.models import PlanDraftSchema, Message, MessageHeader, MessageType
from engine.exceptions import WorkerExecutionError
from engine.prompt_loader import get_prompt_loader

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("firma.audit")

class PlannerWorker:
    """
    PlannerWorker: A strict adapter that converts a PLAN_REQUEST into a PLAN_DRAFT_SUBMITTED.
    
    Rules:
    1. Pure IO: No DB access, no state mutation.
    2. No Auto-Fix: Invalid JSON or Schema violations result in ERROR_REPORT.
    3. No Retries: The worker does not retry; the Engine decides.
    """

    def __init__(self, provider: BaseLLMProvider, model_name: str, dummy_mode: bool = False):
        self.provider = provider
        self.model_name = model_name
        self.dummy_mode = dummy_mode

    async def handle_request(self, project_id: str, user_prompt: str, task_id: str) -> Message:
        """
        Processes a request to create a new plan.
        """
        logger.info(f"[Worker] RECEIVED PLAN REQUEST: project={project_id} task={task_id}")
        if self.dummy_mode:
            logger.info("[Planner] DUMMY_MODE active. Returning Golden Sample Plan.")
            # Hardcoded valid plan draft matching PlanDraftSchema
            dummy_plan = {
                "plan_name": "Corporate Site Golden Sample",
                "tasks": [
                    {
                        "id": "task-golden-1",
                        "role": "CODER",
                        "title": "Implement High-End Corporate Landing Page",
                        "description": "Create a professional dark-themed landing page with inline SVG logo, Tailwind CSS, and a responsive layout.",
                        "acceptance_criteria": [
                            "EXISTS:index.html",
                            "CONTAINS:index.html:<svg",
                            "NOT_EXISTS:logo.svg",
                            "CONTAINS:index.html:Deterministic Kernel"
                        ],
                        "expected_artifacts": ["index.html", "styles.css", "script.js"],
                        "depends_on": []
                    }
                ]
            }
            return Message(
                header=MessageHeader(
                    sender="planner-worker",
                    recipient="engine",
                    message_type=MessageType.WORKER_RESPONSE,
                    plan_id=None
                ),
                payload={
                    "project_id": project_id,
                    "sender_role": "PLANNER",
                    "plan_draft": dummy_plan
                }
            )

        system_prompt = get_prompt_loader().load('planner', 'system')
        user_template = get_prompt_loader().load('planner', 'user_template')
        user_prompt = user_template.format(project_id=project_id, user_prompt=user_prompt)
        
        # We omit the raw Pydantic schema to prevent Model Reflection (Schema Mirroring)
        # We rely on the explicit structural prompt and the Provider's JSON mode.
        schema = None
        
        logger.info(f"[Worker] ABOUT TO CALL PROVIDER: project={project_id} model={self.model_name}")
        start_time = time.time()
        try:
            if hasattr(self.provider, "set_role_context"):
                self.provider.set_role_context(
                    role="PLANNER",
                    task_id=task_id,
                    task_definition={}
                )
            
            # 1. Generate JSON via Provider
            raw_output = await self.provider.generate_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema=schema
            )
            logger.info(f"[Worker] PROVIDER CALL RETURNED: project={project_id} latency={time.time()-start_time:.2f}s")
            
            # DEBUG: Log raw response to file before any processing
            try:
                with open("planner_raw_debug.log", "a", encoding="utf-8") as f:
                    f.write(f"--- REQUEST AT {datetime.now().isoformat()} ---\n")
                    f.write(f"PROVIDER: {self.provider.__class__.__name__}\n")
                    f.write(f"PROMPT: {user_prompt[:200]}...\n")
                    f.write(f"RAW TYPE: {type(raw_output)}\n")
                    if isinstance(raw_output, dict):
                        f.write(f"RAW OUTPUT:\n{json.dumps(raw_output, indent=2)}\n")
                    else:
                        f.write(f"RAW OUTPUT: {str(raw_output)}\n")
                    f.write("-" * 40 + "\n\n")
            except Exception as log_err:
                logger.error(f"Failed to write raw debug log: {log_err}")

            latency = time.time() - start_time
            
            # 2. Robust Unwrapping
            # LLMs sometimes wrap the requested schema in a generic response envelope
            # e.g., { "protocol_version": "1.0", "payload": { "plan_name": "...", "tasks": [...] } }
            processed_output = self._unwrap_schema(raw_output, "plan_name")
            
            # 3. Strict Validation
            validated_plan = PlanDraftSchema.model_validate(processed_output)
            
            # 4. Check for Refusal (empty tasks)
            if not validated_plan.tasks:
                return self._create_error_report(project_id, task_id, "PLANNER_REFUSAL", "LLM provided an empty task list.")

            # Audit Log (Non-blocking, separate from state)
            self._log_audit(user_prompt, raw_output, latency, None)
            
            # 5. Success Message
            return Message(
                header=MessageHeader(
                    sender="planner-worker",
                    recipient="engine",
                    message_type=MessageType.WORKER_RESPONSE,
                    plan_id=None # Plan ID is assigned by the Engine upon submission
                ),
                payload={
                    "project_id": project_id,
                    "task_id": task_id,
                    "event": "PLAN_SUBMITTED",
                    "sender_role": "PLANNER",
                    "plan_draft": validated_plan.model_dump()
                }
            )

        except ValidationError as e:
            latency = time.time() - start_time
            self._log_audit(user_prompt, "ValidationError", latency, str(e))
            return self._create_error_report(project_id, task_id, "SCHEMA_VIOLATION", str(e))
        except WorkerExecutionError:
            # Let this propagate to the worker loop for deterministic governance mapping
            raise
        except Exception as e:
            latency = time.time() - start_time
            self._log_audit(user_prompt, "Exception", latency, str(e))
            return self._create_error_report(project_id, task_id, "LLM_INTERNAL_ERROR", str(e))

    def _unwrap_schema(self, data: Any, required_key: str) -> Any:
        """
        Attempts to extract the relevant schema object from a potentially wrapped LLM response.
        Handles both protocol envelopes and generic LLM wrappers.
        """
        if not isinstance(data, dict):
            # Try to parse as JSON if it's a string
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                    if not isinstance(data, dict):
                        return data
                except json.JSONDecodeError:
                    return data
            return data
        
        # 1. If the required key is already at the top level, we are good
        if required_key in data:
            return data
            
        # 2. Check for the Firma Protocol Envelope ('payload' key)
        if "payload" in data and isinstance(data["payload"], dict):
            if required_key in data["payload"]:
                return data["payload"]
            # Recurse into payload in case it's double-wrapped
            return self._unwrap_schema(data["payload"], required_key)
                
        # 3. Look for common LLM wrapper keys
        for key in ["plan", "result", "data", "response"]:
            if key in data and isinstance(data[key], dict) and required_key in data[key]:
                return data[key]
                
        return data

    def _create_error_report(self, project_id: str, task_id: str, error_code: str, detail: str) -> Message:
        return Message(
            header=MessageHeader(
                sender="planner-worker",
                recipient="engine",
                message_type=MessageType.WORKER_RESPONSE,
                plan_id=None
            ),
            payload={
                "project_id": project_id,
                "task_id": task_id,
                "event": "TASK_FAILED",
                "sender_role": "PLANNER",
                "error_code": error_code,
                "detail": detail
            }
        )

    def _log_audit(self, prompt: str, output: Any, latency: float, error: Optional[str]):
        audit_logger.info(
            f"PLANNER_AUDIT | model: {self.model_name} | latency: {latency:.2f}s | "
            f"error: {error} | prompt: {prompt[:100]}... | output: {str(output)[:500]}"
        )
