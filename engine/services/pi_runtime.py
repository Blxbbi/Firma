import asyncio
import json
import uuid
import logging
from typing import Any, Dict, Optional
from nats.aio.client import Client as NATS
from nats.aio.errors import ErrTimeout as NATSTimeoutError

logger = logging.getLogger(__name__)

class SwarmClient:
    """
    SwarmClient: An internal API for interacting with the Pi-Messenger Swarm.
    Bypasses the CLI and communicates directly via NATS.
    """

    def __init__(self, nats_url: str = "nats://localhost:4222"):
        self.nats_url = nats_url
        self._nc: Optional[NATS] = None

    async def connect(self):
        """Establishes a connection to the NATS server."""
        if self._nc is None:
            self._nc = NATS()
            try:
                await self._nc.connect(self.nats_url)
                logger.info(f"Internal SwarmClient connected to NATS at {self.nats_url}")
            except Exception as e:
                logger.error(f"Failed to connect to NATS at {self.nats_url}: {str(e)}")
                raise e

    async def disconnect(self):
        """Closes the NATS connection."""
        if self._nc:
            await self._nc.close()
            self._nc = None
            logger.info("Internal SwarmClient disconnected from NATS")

    async def request(self, agent_subject: str, payload: Dict[str, Any], task_id: str, timeout: int = 60) -> Any:
        """
        Simulates the full Engine transport loop.
        1. Publishes to agent_subject via JetStream.
        2. Waits for a response on 'kernel.responses' matching the task_id.
        """
        if not self._nc:
            await self.connect()

        # Use JetStream for publishing to ensure pull-consumers can fetch it
        js = self._nc.jetstream()

        # Construct the swarm envelope
        envelope = {
            "protocol_version": "1.0",
            "message_id": str(uuid.uuid4()),
            "payload": {
                "task_id": task_id,
                "state_revision": payload.get("state_revision", 1),
                **payload
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        try:
            # Publish to the stream
            await js.publish(agent_subject, json.dumps(envelope).encode())
            logger.info(f"Published task {task_id} to {agent_subject} via JetStream")

            # 2. Listen for the response on kernel.responses
            response_queue = asyncio.Queue()
            
            async def response_handler(msg):
                try:
                    data = json.loads(msg.data.decode())
                    # Check if this is the response for our task
                    payload = data.get("payload", data)
                    if payload.get("task_id") == task_id:
                        await response_queue.put(payload)
                except Exception as e:
                    logger.debug(f"Ignored non-relevant message: {e}")

            # Subscribe to the response subject
            sub = await self._nc.subscribe("kernel.responses", cb=response_handler)
            
            try:
                # Wait for the specific response to appear in the queue
                response = await asyncio.wait_for(response_queue.get(), timeout=timeout)
                return response
            except asyncio.TimeoutError:
                logger.error(f"Timeout waiting for task {task_id} response on kernel.responses")
                raise TimeoutError(f"Worker failed to respond to task {task_id} within {timeout}s")
            finally:
                await sub.unsubscribe()

        except Exception as e:
            logger.error(f"Internal API Error during request to {agent_subject}: {str(e)}")
            raise e


    async def send(self, to: str, message: str):
        """Simple fire-and-forget send."""
        if not self._nc:
            await self.connect()
        
        subject = f"swarm.agent.{to}"
        await self._nc.publish(subject, message.encode())

from datetime import datetime, timezone
