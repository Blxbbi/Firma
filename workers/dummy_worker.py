import time
import logging
from typing import Callable, Any
from engine.models import Message, MessageType, PlanDraftSchema

logger = logging.getLogger(__name__)

class DummyWorker:
    """
    A minimal worker designed for infrastructure testing.
    It communicates solely via the provided messenger callback.
    """

    def __init__(self, messenger_send_callback: Callable[[Message], None], mode: str = "happy"):
        self.send = messenger_send_callback
        self.mode = mode

    def handle_message(self, message: Message):
        """
        The core logic of the worker, reacting to incoming messages.
        """
        msg_type = message.header.message_type
        logger.info(f"[Worker] Received {msg_type.value}")

        if msg_type == MessageType.TASK_ASSIGNMENT:
            self._handle_assignment(message)
        elif msg_type == MessageType.PLAN_REQUEST:
            self._handle_plan_request(message)

    def _handle_assignment(self, message: Message):
        task_id = message.payload.get("task_id")
        plan_id = message.header.plan_id

        if self.mode == "double_ack":
            # Send two ACKs
            self._send_ack(task_id, plan_id)
            self._send_ack(task_id, plan_id)
            return

        if self.mode == "no_ack":
            # Skip ACK, go straight to RESULT
            time.sleep(0.1)
            self._send_result(task_id, plan_id)
            return

        if self.mode == "late_result":
            # Send ACK immediately, but delay the RESULT significantly
            self._send_ack(task_id, plan_id)
            time.sleep(2.0) # Longer than the scheduler timeout in the test
            self._send_result(task_id, plan_id)
            return

        # Happy Path
        self._send_ack(task_id, plan_id)
        time.sleep(0.1)
        self._send_result(task_id, plan_id)

    def _handle_plan_request(self, message: Message):
        # For testing the whole loop
        plan_name = message.payload.get("goal", "Dummy Plan")
        draft = PlanDraftSchema(
            plan_name=plan_name,
            tasks=[{
                "id": "T1",
                "description": "Dummy Task",
                "dependencies": [],
                "expected_artifacts": ["dummy.txt"],
                "acceptance_criteria": ["exists"]
            }]
        )
        
        response = Message(
            header={
                "sender": "Worker",
                "recipient": "Engine",
                "message_type": MessageType.PLAN_DRAFT_SUBMITTED,
                "plan_id": None # New plan
            },
            payload=draft.model_dump()
        )
        self.send(response)

    def _send_ack(self, task_id: str, plan_id: str):
        ack = Message(
            header={
                "sender": "Worker",
                "recipient": "Engine",
                "message_type": MessageType.TASK_ACK,
                "plan_id": plan_id
            },
            payload={"task_id": task_id, "worker_id": "dummy-worker"}
        )
        self.send(ack)

    def _send_result(self, task_id: str, plan_id: str):
        result = Message(
            header={
                "sender": "Worker",
                "recipient": "Engine",
                "message_type": MessageType.TASK_RESULT,
                "plan_id": plan_id
            },
            payload={
                "task_id": task_id,
                "artifacts": [{"path": "dummy.txt", "content": "hello"}]
            }
        )
        self.send(result)
