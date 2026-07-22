import json
import logging
from engine.models import Message, MessageHeader, MessageType, PlannerOutput
from engine.providers.base import LLMProvider

logger = logging.getLogger(__name__)

class PlannerWorker:
    def __init__(self, messenger, provider: LLMProvider):
        self.messenger = messenger
        self.provider = provider
        self.system_prompt = """You are a deterministic technical planning engine.

Your ONLY job is to convert a high-level goal into a strictly structured JSON plan.

You must obey ALL rules below without exception.

----------------------------------------
GLOBAL RULES
----------------------------------------

1. Output MUST be valid JSON.
2. Output MUST match the required schema exactly.
3. Output MUST contain NO prose, NO explanations, NO markdown.
4. Maximum 3 tasks.
5. Tasks must form a STRICT linear chain:
   - Task 1: no dependencies
   - Task 2: depends only on Task 1
   - Task 3: depends only on Task 2
6. Each task must produce or modify EXACTLY ONE file.
7. No test files.
8. No README.
9. No comments about the process.
10. No TODO placeholders.

----------------------------------------
ACCEPTANCE CRITERIA FORMAT (MANDATORY)
----------------------------------------

Acceptance criteria must use ONLY the following machine-readable formats:

- EXISTS:<relative_path>
- CMD:<command>:<expected_output>

Examples:
- EXISTS:main.py
- CMD:python main.py 2 3:5

No other format is allowed.

----------------------------------------
EXPECTED ARTIFACT RULES
----------------------------------------

Each task must define:

- id (string)
- description (clear and concrete)
- dependencies (list)
- expected_artifacts (list of exactly ONE object)
- acceptance_criteria (list)

Each expected_artifacts item must contain:
- path (relative path, no absolute paths, no "..")
- type ("CREATE" or "UPDATE")

----------------------------------------
FAILURE BEHAVIOR
----------------------------------------

If the goal cannot be decomposed under these constraints,
return an empty JSON object:

{}
"""

    def handle_message(self, message: Message):
        if message.header.message_type == MessageType.PLAN_REQUEST:
            self._process_plan_request(message)

    def _process_plan_request(self, message: Message):
        goal = message.payload.get("goal")
        if not goal:
            logger.error("PlannerWorker: Received PLAN_REQUEST without goal.")
            return

        logger.info(f"PlannerWorker: Generating plan for goal: '{goal}'")
        
        try:
            # 1. Generate raw output (prepend system prompt to user prompt)
            user_prompt = f"Goal:\n\"{goal}\"\n\nGenerate the structured plan."
            full_prompt = f"{self.system_prompt}\n\n{user_prompt}"
            raw_response = self.provider.generate(full_prompt)
            
            # 2. Parse JSON
            plan_data = json.loads(raw_response)
            
            if not plan_data:
                logger.warning("PlannerWorker: LLM returned empty JSON (Refusal).")
                self._send_error(message, "PLAN_REFUSED", "The goal could not be decomposed into a valid plan.")
                return

            # 3. Validate Schema
            plan_output = PlannerOutput(**plan_data)
            logger.info(f"PlannerWorker: Plan successfully generated: {plan_output.plan_name}")

            # 4. Send Result
            result_msg = Message(
                header=MessageHeader(
                    sender="PlannerWorker",
                    recipient="Engine",
                    message_type=MessageType.PLAN_DRAFT_SUBMITTED,
                    plan_id=message.header.plan_id
                ),
                payload=plan_output.model_dump()
            )
            self.messenger(result_msg)

        except json.JSONDecodeError as e:
            logger.error(f"PlannerWorker: Invalid JSON response: {str(e)}")
            self._send_error(message, "LLM_INVALID_JSON", f"Failed to parse LLM response as JSON: {str(e)}")
        except Exception as e:
            # This catches Pydantic ValidationErrors and other unexpected issues
            logger.error(f"PlannerWorker: Plan generation failed: {str(e)}")
            self._send_error(message, "LLM_SCHEMA_VIOLATION", f"Plan failed validation: {str(e)}")

    def _send_error(self, original_message: Message, error_code: str, reason: str):
        error_msg = Message(
            header=MessageHeader(
                sender="PlannerWorker",
                recipient="Engine",
                message_type=MessageType.ERROR_REPORT,
                plan_id=original_message.header.plan_id
            ),
            payload={"error_code": error_code, "reason": reason}
        )
        self.messenger(error_msg)
