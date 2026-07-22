import logging
import random
import time
import asyncio
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Callable, Awaitable
from collections import deque
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class TransportMessage:
    """
    Encapsulates a received message and its transport-specific acknowledgement handle.
    This keeps the Kernel transport-agnostic while allowing explicit ACKs.
    """
    envelope: Dict[str, Any]
    _ack_handle: Callable[[], Awaitable[None]]

    async def ack(self) -> None:
        """Triggers the acknowledgement of this message in the underlying transport."""
        await self._ack_handle()

class WorkerTransport(ABC):
    """
    Minimalist, mesh-compatible transport interface.
    Handles raw dict payloads to avoid business-logic coupling.
    """
    @abstractmethod
    async def dispatch(self, payload: Dict[str, Any]) -> None:
        """Send a message to a worker (Fire-and-Forget)."""
        pass

    @abstractmethod
    async def poll(self) -> List[TransportMessage]:
        """Retrieve all available responses as TransportMessage objects."""
        pass

class LocalTransport(WorkerTransport):
    """
    Baseline Local Transport.
    Simulates a message queue using internal buffers.
    """
    def __init__(self, worker_executor_callback=None):
        # Responses waiting to be polled by the Kernel
        self._incoming_queue = deque()
        # Callback to simulate the Worker's logic (e.g. ExecutionService)
        self._worker_executor = worker_executor_callback

    async def dispatch(self, payload: Dict[str, Any]) -> None:
        """
        For LocalTransport, dispatching immediately triggers the worker
        to simulate a response being generated.
        """
        logger.debug(f"[LocalTransport] Dispatching payload: {payload.get('task_id')}")
        
        if self._worker_executor:
            # We await the executor since it might be async
            await self._worker_executor(payload)
        else:
            logger.warning("[LocalTransport] No worker executor configured. Payload lost.")

    async def poll(self) -> List[TransportMessage]:
        """Retrieve all accumulated responses wrapped in TransportMessage."""
        responses = []
        while self._incoming_queue:
            payload = self._incoming_queue.popleft()
            # LocalTransport uses a no-op ack
            async def no_op_ack():
                pass
            
            responses.append(TransportMessage(
                envelope={"payload": payload}, # LocalTransport is simple, just wraps payload
                _ack_handle=no_op_ack
            ))
        return responses

    def simulate_worker_response(self, response_payload: Dict[str, Any]):
        """Helper for the worker executor to push a response back."""
        self._incoming_queue.append(response_payload)

class ChaosTransport(WorkerTransport):
    """
    Network Chaos Layer.
    Wraps a base transport and injects non-deterministic failures.
    """
    def __init__(self, base_transport: WorkerTransport, 
                 delay_range=(0, 0.2), 
                 drop_prob=0.0, 
                 dup_prob=0.0, 
                 reorder_prob=0.0,
                 partial_prob=0.0):
        self.base = base_transport
        self.delay_range = delay_range
        self.drop_prob = drop_prob
        self.dup_prob = dup_prob
        self.reorder_prob = reorder_prob
        self.partial_prob = partial_prob
        
        # Buffer for delayed messages (timestamp, payload)
        self._delayed_responses = []

    async def dispatch(self, payload: Dict[str, Any]) -> None:
        """Dispatch with potential delay/drop."""
        if random.random() < self.drop_prob:
            logger.warning(f"[Chaos] DROPPED dispatch for {payload.get('task_id')}")
            return

        # Simulate network latency before sending
        delay = random.uniform(*self.delay_range)
        if delay > 0:
            await asyncio.sleep(delay)
            
        await self.base.dispatch(payload)

    async def poll(self) -> List[TransportMessage]:
        """Poll with duplication, reordering, and partial delivery."""
        # 1. Get base responses (these are now TransportMessage objects)
        responses = await self.base.poll()
        
        # 2. Inject Delayed Duplicates (Zombie Network)
        self._delayed_responses.extend(responses)
        if len(self._delayed_responses) > 100:
            self._delayed_responses = self._delayed_responses[-100:]

        # 3. Duplicate existing responses
        final_responses = []
        for r in responses:
            final_responses.append(r)
            if random.random() < self.dup_prob:
                logger.debug(f"[Chaos] DUPLICATING response for {r.envelope.get('payload', {}).get('task_id')}")
                final_responses.append(r)

        # 4. Reorder responses
        if random.random() < self.reorder_prob and len(final_responses) > 1:
            logger.debug("[Chaos] SHUFFLING responses")
            random.shuffle(final_responses)

        # 5. Partial Delivery
        if random.random() < self.partial_prob and len(final_responses) > 1:
            split_idx = random.randint(1, len(final_responses) - 1)
            logger.debug(f"[Chaos] PARTIAL delivery: keeping {split_idx}/{len(final_responses)}")
            self._delayed_responses.extend(final_responses[split_idx:])
            final_responses = final_responses[:split_idx]

        # 6. Inject Zombies from history
        if random.random() < self.dup_prob and self._delayed_responses:
            zombie = random.choice(self._delayed_responses)
            logger.debug(f"[Chaos] ZOMBIE response for {zombie.envelope.get('payload', {}).get('task_id')}")
            final_responses.append(zombie)

        return final_responses
