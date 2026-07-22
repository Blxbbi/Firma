import logging
import uuid
from typing import Dict, Any
from datetime import datetime, timezone
from engine.db import DatabaseManager
from engine.repository import MessageRepository
from engine.services.execution import ExecutionService

logger = logging.getLogger(__name__)

class LocalWorkerBridge:
    """
    Bridges the LocalTransport to the actual ExecutionService.
    Acts as a "Simulated Worker" that the LocalTransport can call.
    """
    def __init__(self, db_manager: DatabaseManager, execution_service: ExecutionService, transport):
        self.db = db_manager
        self.execution_service = execution_service
        self.transport = transport

    async def handle_assignment(self, payload: Dict[str, Any]):
        """
        Simulates a worker receiving a TASK_ASSIGNMENT and responding.
        """
        task_id = payload.get("task_id")
        if not task_id:
            return

        logger.info(f"[WorkerBridge] Received assignment for task {task_id}. Processing...")

        try:
            with self.db.session_scope() as session:
                repo = MessageRepository(session)
                task = repo.get_task_by_id(session, task_id)
                if not task:
                    logger.error(f"[WorkerBridge] Task {task_id} not found in DB.")
                    return

                # 1. Perform the actual execution (Sandbox)
                result = await self.execution_service.execute(
                    session, 
                    task.plan.project_id, 
                    task.plan.id, 
                    task.plan.version, 
                    task_id
                )

                # 2. Construct a WorkerResponse (The "Untrusted Proposal")
                event = "VERIFY_SUCCESS" if result.success else "VERIFY_FAILURE"
                
                response_payload = {
                    "message_id": str(uuid.uuid4()),
                    "task_id": task_id,
                    "event": event,
                    "state_revision": task.state_revision,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "artifacts": {
                        "files": [] 
                    }
                }
                
                # 3. Push the response back to the transport
                self.transport.simulate_worker_response(response_payload)
                logger.info(f"[WorkerBridge] Sent response {event} for task {task_id}")

        except Exception as e:
            logger.exception(f"[WorkerBridge] Critical failure handling task {task_id}: {str(e)}")
