import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Awaitable, List, Dict, Any, Optional

from nats.aio.client import Client as NATS
from nats.js.api import ConsumerConfig
from engine.transport.base import WorkerTransport, TransportMessage

# ============================================================
# PiMessengerTransport (NATS + JetStream)
# ============================================================

class PiMessengerTransport(WorkerTransport):
    """
    Minimaler JetStream Pull-Transport.
    - TASK_DISPATCH -> tasks.<ROLE>
    - WORKER_RESPONSE -> kernel.responses
    """

    PROTOCOL_VERSION = "1.0"

    def __init__(
        self,
        nats_url: str = "nats://localhost:4222",
        kernel_consumer: str = "kernel-consumer",
        responses_stream: str = "RESPONSES",
        poll_batch_size: int = 10,
        poll_timeout: float = 0.1,
        sender_id: str = "kernel-01",
    ):
        self._nats_url = nats_url
        self._kernel_consumer = kernel_consumer
        self._responses_stream = responses_stream
        self._poll_batch_size = poll_batch_size
        self._poll_timeout = poll_timeout
        self._sender_id = sender_id

        self._nc: Optional[NATS] = None
        self._js = None
        self._sub = None

    # --------------------------------------------------------
    # Connection Lifecycle
    # --------------------------------------------------------

    async def connect(self) -> None:
        connected = False
        for i in range(5):
            try:
                print(f"Connecting to NATS at {self._nats_url} (attempt {i+1})...")
                self._nc = NATS()
                await self._nc.connect(self._nats_url)
                print(f"Connected! Client: {self._nc}")
                connected = True
                break
            except Exception as e:
                print(f"Transport connection attempt {i+1} failed: {e}")
                await asyncio.sleep(2)
        
        if not connected or self._nc is None:
            raise RuntimeError(f"Could not connect to NATS at {self._nats_url}")

        self._js = self._nc.jetstream()

        # Pull subscription auf durable consumer
        self._sub = await self._js.pull_subscribe(
            subject="kernel.responses",
            durable=self._kernel_consumer,
            stream=self._responses_stream,
        )

    async def close(self) -> None:
        if self._nc:
            await self._nc.drain()
            await self._nc.close()

    # --------------------------------------------------------
    # DISPATCH (Kernel -> Worker)
    # --------------------------------------------------------

    async def dispatch(self, payload: Dict[str, Any]) -> None:
        """
        Payload enthält:
        - task_id
        - assigned_role
        - execution_phase
        - state_revision
        - context
        """

        assigned_role = payload.get("assigned_role")
        if not assigned_role:
            raise ValueError("dispatch payload missing assigned_role")

        subject = f"tasks.{assigned_role}"

        envelope = self._build_envelope(
            message_type="TASK_DISPATCH",
            role="KERNEL",
            correlation_id=str(uuid.uuid4()),
            payload=payload,
        )

        await self._js.publish(
            subject,
            json.dumps(envelope).encode("utf-8"),
        )

    async def publish_response(
        self,
        role: str,
        payload: Dict[str, Any],
        correlation_id: Optional[str] = None,
    ) -> None:
        """
        Helper for Workers to send responses back to the Kernel.
        """
        if not self._js:
            raise RuntimeError("Transport not connected")

        envelope = self._build_envelope(
            message_type="WORKER_RESPONSE",
            role=role,
            correlation_id=correlation_id or str(uuid.uuid4()),
            payload=payload,
        )

        await self._js.publish(
            "kernel.responses",
            json.dumps(envelope).encode("utf-8"),
        )

    async def poll(self) -> List[TransportMessage]:
        """
        Pullt Messages vom kernel.responses Stream.
        """

        if not self._sub:
            raise RuntimeError("Transport not connected")

        try:
            msgs = await self._sub.fetch(
                batch=self._poll_batch_size,
                timeout=self._poll_timeout,
            )
        except asyncio.TimeoutError:
            return []

        transport_messages: List[TransportMessage] = []

        for msg in msgs:
            try:
                envelope = self._extract_envelope(msg)
            except Exception:
                # Envelope kaputt -> trotzdem ack, sonst infinite redelivery
                await msg.ack()
                continue

            transport_messages.append(
                TransportMessage(
                    envelope=envelope,
                    _ack_handle=msg.ack,
                )
            )

        return transport_messages

    # --------------------------------------------------------
    # Envelope Handling (Wire v1.0)
    # --------------------------------------------------------

    def _build_envelope(
        self,
        message_type: str,
        role: str,
        correlation_id: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "protocol_version": self.PROTOCOL_VERSION,
            "message_type": message_type,
            "message_id": str(uuid.uuid4()),
            "correlation_id": correlation_id,
            "sender_id": self._sender_id,
            "role": role,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }

    def _extract_envelope(self, msg) -> Dict[str, Any]:
        """
        Minimale Transport-Validierung.
        Business-Validierung passiert im Guardian.
        """

        data = json.loads(msg.data.decode("utf-8"))

        if not isinstance(data, dict):
            raise ValueError("Invalid envelope format")

        if data.get("protocol_version") != self.PROTOCOL_VERSION:
            raise ValueError("Unsupported protocol version")

        if data.get("message_type") != "WORKER_RESPONSE":
            raise ValueError("Invalid message_type for kernel poll")

        if "payload" not in data:
            raise ValueError("Missing payload")

        return data
