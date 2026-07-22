import asyncio
import uuid
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from engine.transport.base import WorkerTransport, TransportMessage

logger = logging.getLogger(__name__)

class InternalTransport(WorkerTransport):
    """
    High-performance in-memory transport for benchmarks.
    Eliminates network jitter to isolate Engine Kernel performance.
    """
    def __init__(self):
        self._queue = asyncio.Queue()
        self._dispatch_queue = asyncio.Queue()
        self.PROTOCOL_VERSION = "1.0"

    async def connect(self):
        pass

    async def close(self):
        pass

    async def dispatch(self, payload: Dict[str, Any]) -> None:
        """Sends a message from the Engine to a Worker."""
        task_id = payload.get("task_id", "unknown")
        run_id = payload.get("run_id", "unknown")
        
        try:
            logger.info(f"[Transport] PUTTING dispatch for task {task_id} (Run {run_id})")
            await self._dispatch_queue.put(payload)
            logger.info(f"[Transport] Assignment enqueued for worker. Task: {task_id}")
        except Exception as e:
            logger.exception(f"[Transport] Dispatch failed critically for task {task_id}: {e}")
            raise

    async def publish_response(self, role: str, payload: Dict[str, Any], correlation_id: Optional[str] = None) -> None:
        # Mimics a worker sending a response
        # Use message_id from payload if available, otherwise generate a unique one
        msg_id = payload.get("message_id", f"msg-{uuid.uuid4()}")
        
        envelope = {
            "protocol_version": self.PROTOCOL_VERSION,
            "message_type": "WORKER_RESPONSE",
            "message_id": msg_id,
            "correlation_id": correlation_id or "mock-corr",
            "sender_id": "mock-worker",
            "role": role,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        
        async def ack():
            pass

        await self._queue.put(TransportMessage(envelope=envelope, _ack_handle=ack))

    async def poll(self) -> List[TransportMessage]:
        messages = []
        try:
            # Poll everything currently in the queue
            while not self._queue.empty():
                messages.append(await self._queue.get())
        except Exception:
            pass
        return messages

    async def get_dispatch(self) -> Dict[str, Any]:
        """
        Blocking call to retrieve a message destined for a worker.
        This is the industrial way: wait until a message actually arrives.
        """
        logger.info(f"[Transport] GET_DISPATCH CALL - Queue size: {self._dispatch_queue.qsize()}")
        res = await self._dispatch_queue.get()
        logger.info(f"[Transport] GET_DISPATCH RETURNED: {res.get('task_id', 'unknown')}")
        return res

    async def send_message(self, payload: Dict[str, Any]):
        """Used by the Benchmark Runner to inject mock responses."""
        await self.publish_response(
            role=payload.get("sender_role", "CODER"),
            payload=payload
        )
