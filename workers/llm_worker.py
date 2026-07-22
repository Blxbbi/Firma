import logging
import json
from typing import Callable
from engine.models import Message, MessageType, MessageHeader, LLMResponse
from engine.providers.base import LLMProvider
from pydantic import ValidationError

logger = logging.getLogger(__name__)

class LLMWorker:
    """
    A worker that interacts with an LLM to generate code changes.
    Follows a strict parsing and validation pipeline.
    """

    def __init__(self, messenger_send_callback: Callable[[Message], None], provider: LLMProvider):
        self.send = messenger_send_callback
        self.provider = provider

    def handle_message(self, message: Message):
        """
        Core logic: Receive assignment -> Prompt LLM -> Validate -> Send Result/Error.
        """
        msg_type = message.header.message_type
        logger.info(f"[LLMWorker] Received {msg_type}")

        if msg_type == MessageType.TASK_ASSIGNMENT:
            self._process_task(message)

    def _process_task(self, message: Message):
        task_id = message.payload.get("task_id")
        plan_id = message.header.plan_id
        
        # In a real worker, we would build a prompt from the task description
        # For now, we use a placeholder.
        prompt = f"Generate code for task: {task_id}"

        logger.info(f"[LLMWorker] Prompting LLM for task {task_id}...")

        try:
            # 1. Generate raw output
            raw_output = self.provider.generate(prompt)
            logger.debug(f"[LLMWorker] Raw LLM Output: {repr(raw_output)}")

            # 2. Parse JSON
            try:
                data = json.loads(raw_output)
            except json.JSONDecodeError as e:
                self._send_error(task_id, plan_id, "LLM_INVALID_JSON", f"JSON Parse Error: {str(e)}")
                return

            # 3. Validate against Schema
            try:
                response = LLMResponse.model_validate(data)
            except ValidationError as e:
                self._send_error(task_id, plan_id, "LLM_SCHEMA_VIOLATION", f"Schema Validation Error: {str(e)}")
                return

            # 4. Success! Send Task Result
            # Note: The worker DOES NOT write files. It only sends the intended changes.
            result_msg = Message(
                header=MessageHeader(
                    sender="LLMWorker",
                    recipient="Engine",
                    message_type=MessageType.WORKER_RESPONSE,
                    plan_id=plan_id
                ),
                payload={
                    "task_id": task_id,
                    "event": "CODE_SUBMITTED",
                    "artifacts": [a.model_dump() for a in response.artifacts],
                    "logs": "LLM successfully generated artifacts."
                }
            )
            self.send(result_msg)
            logger.info(f"[LLMWorker] Successfully sent WORKER_RESPONSE for task {task_id}")

        except Exception as e:
            logger.exception(f"[LLMWorker] Unexpected error during task {task_id}")
            self._send_error(task_id, plan_id, "LLM_INTERNAL_ERROR", str(e))

    def _send_error(self, task_id: str, plan_id: str, error_code: str, reason: str):
        """Sends a failure response message to the engine."""
        error_msg = Message(
            header=MessageHeader(
                sender="LLMWorker",
                recipient="Engine",
                message_type=MessageType.WORKER_RESPONSE,
                plan_id=plan_id
            ),
            payload={
                "task_id": task_id,
                "event": "TASK_FAILED",
                "logs": f"Error {error_code}: {reason}"
            }
        )
        self.send(error_msg)
        logger.error(f"[LLMWorker] Sent WORKER_RESPONSE (TASK_FAILED) for task {task_id}: {error_code} - {reason}")
