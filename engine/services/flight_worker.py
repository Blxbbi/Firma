import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from engine.models import WorkerResponse, TaskEvent, AssignedRole
from engine.providers.pi_provider import PiProvider

logger = logging.getLogger(__name__)

class FlightWorker:
    """
    FlightWorker: A specialized worker for the Flight Program.
    It uses a PiProvider to generate structured WorkerResponses that 
    adhere to the Engine's Artifact Contract.
    """

    def __init__(self, provider: PiProvider):
        self.provider = provider

    async def generate_response(self, task_id: str, state_revision: int, prompt: str, model_name: str = "gpt-4o") -> Dict[str, Any]:
        """
        Simulates the Engine's dispatch to a worker via the Internal API.
        """
        # Payload formatted for the CoderAgent's build_prompts logic
        payload = {
            "task_id": task_id,
            "state_revision": state_revision,
            "description": prompt,
            "acceptance_criteria": [],
            "existing_artifacts": [],
            "message_id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        try:
            # Use the internal SwarmClient to publish and wait for response on kernel.responses
            response = await self.provider.client.request(
                agent_subject="tasks.CODER",
                payload=payload,
                task_id=task_id,
                timeout=60
            )
            
            # The CoderAgent returns a payload with 'event', 'artifacts', etc.
            # We ensure it's correctly formatted for the Guardian.
            if not isinstance(response, dict):
                raise ValueError(f"Worker returned non-dict response: {response}")
                
            # Normalize for the Guardian
            response["message_id"] = response.get("message_id", str(uuid.uuid4()))
            response["task_id"] = task_id
            response["state_revision"] = state_revision
            response["sender_role"] = "CODER"
            response["timestamp"] = response.get("timestamp", datetime.now(timezone.utc).isoformat())
            
            return response
        except Exception as e:
            logger.error(f"FlightWorker failed to get response for {task_id}: {str(e)}")
            return {"error": "Worker failure", "message": str(e)}
