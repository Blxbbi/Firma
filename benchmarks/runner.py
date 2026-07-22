import asyncio
import random
import time
import logging
import uuid
from typing import Optional
from benchmarks.profiles import LoadProfile
from engine.services.telemetry import telemetry
from engine.services.concurrency import concurrency_controller
from engine.providers.stochastic_llm_provider import stochastic_provider

logger = logging.getLogger("benchmark.runner")

class FlightSimulator:
    """
    Simulates a single Flight's journey through the engine.
    Synchronizes with the DB to ensure revisions are correct.
    """
    def __init__(self, profile: LoadProfile, project_id: str, task_id: str, transport, db_manager, run_id: str, stage_id: str):
        self.profile = profile
        self.project_id = project_id
        self.task_id = task_id
        self.transport = transport
        self.db_manager = db_manager
        self.run_id = run_id
        self.stage_id = stage_id

    async def _sync_revision(self) -> Optional[int]:
        """Helper to get current task revision from DB."""
        try:
            async with self.db_manager.session_scope() as session:
                from engine.models import Task
                from sqlalchemy import select
                result = await session.execute(select(Task).where(Task.id == self.task_id))
                task = result.scalar_one_or_none()
                if not task: return None
                return task.state_revision
        except Exception as e:
            logger.error(f"Failed to sync revision for {self.task_id}: {e}")
            return None

    async def _wait_for_transition(self, old_revision: int, timeout: float = 0.5) -> bool:
        """Polls the DB until the task revision increments or timeout occurs."""
        start = time.time()
        while time.time() - start < timeout:
            rev = await self._sync_revision()
            if rev is not None and rev > old_revision:
                return True
            await asyncio.sleep(0.02) # Poll every 20ms
        return False

    async def run(self, stop_event: asyncio.Event):
        """
        Executes the flight based on the profile with CAS-aware retries.
        """
        # 1. Sync initial state from DB
        current_revision = await self._sync_revision()
        if current_revision is None:
            return

        # 2. Simulate the sequence of transitions defined in the profile
        for i in range(self.profile.transitions_per_flight):
            if stop_event.is_set():
                break
            
            # Use Stochastic LLM Provider for realistic external pressure
            try:
                await stochastic_provider.generate(f"Task {self.task_id} prompt")
            except Exception as e:
                logger.debug(f"Stochastic Provider simulated error: {e}")
                # If it's a rate limit or error, the flight may fail or retry
                # For the benchmark, we treat it as a failure to transition
                return
            
            # Transition attempt loop (CAS Retry Logic)
            attempts = 0
            transition_success = False
            
            while attempts < 5 and not transition_success:
                attempts += 1
                
                # Sync revision AND state before sending to ensure we are not sending to a terminal task
                try:
                    async with self.db_manager.session_scope() as session:
                        from engine.models import Task, ExecutionPhase
                        from sqlalchemy import select
                        result = await session.execute(select(Task).where(Task.id == self.task_id))
                        task = result.scalar_one_or_none()
                        if not task: break
                        
                        # BREAK if task has reached a terminal state
                        if task.state in {ExecutionPhase.COMPLETE, ExecutionPhase.FAILED, ExecutionPhase.FAILED_ITERATION_LIMIT}:
                            logger.info(f"Task {self.task_id} reached terminal state {task.state}. Stopping simulator.")
                            return # Terminal state reached, flight ends
                            
                        current_revision = task.state_revision
                except Exception as e:
                    logger.error(f"Failed to sync state for {self.task_id}: {e}")
                    break

                # Create a mock response
                msg_id = f"{self.run_id}-{self.stage_id}-{uuid.uuid4()}"
                response = {
                    "protocol_version": "1.0",
                    "message_id": msg_id,
                    "task_id": self.task_id,
                    "state_revision": current_revision, 
                    "sender_role": "CODER",
                    "event": "CODE_SUBMITTED",
                    "timestamp": time.time(),
                    "artifacts": {
                        "files": [
                            {"path": f"file_{j}.py", "content": "x" * self.profile.artifact_size_bytes, "action": "CREATE"}
                            for j in range(self.profile.artifact_count)
                        ]
                    },
                    "logs": f"Benchmark flight execution - Attempt {attempts}"
                }
                
                await self.transport.send_message(response)
                
                # Wait for the Engine to process and increment the revision
                if await self._wait_for_transition(current_revision):
                    transition_success = True
                    if attempts > 1:
                        telemetry.increment("cas_successful_retries")
                else:
                    # CAS failure or slow processing
                    if attempts > 1:
                        telemetry.increment("cas_retry_depth")
                    logger.debug(f"CAS conflict or timeout for {self.task_id} on attempt {attempts}")

            if not transition_success:
                logger.warning(f"Flight {self.task_id} failed to transition after {attempts} attempts.")
                break
            
            # Gap between transitions to avoid instant flooding
            if self.profile.inter_transition_delay[0] > 0 or self.profile.inter_transition_delay[1] > 0:
                delay = random.uniform(*self.profile.inter_transition_delay)
                await asyncio.sleep(delay)


async def run_stage(profile: LoadProfile, concurrency: int, duration_s: int, transport, stop_event: asyncio.Event, task_ids: list[str], db_manager, run_id: str, stage_id: str):
    """
    Maintains a steady-state load for a given duration.
    """
    start_time = time.time()
    
    # Keep track of active flights
    active_flights = []
    
    # Task ID pool for simulators
    task_pool = asyncio.Queue()
    for tid in task_ids:
        task_pool.put_nowait(tid)
    
    async def flight_wrapper():
        try:
            # Get a task from the pool
            t_id = await task_pool.get()
            
            # Use the stage-specific db_manager and run_id
            sim = FlightSimulator(profile, "UNKNOWN", t_id, transport, db_manager, run_id, stage_id)
            
            # Check if task is already terminal before running
            async with db_manager.session_scope() as session:
                from engine.models import Task, ExecutionPhase
                from sqlalchemy import select
                result = await session.execute(select(Task).where(Task.id == t_id))
                task = result.scalar_one_or_none()
                if task and task.state in {ExecutionPhase.COMPLETE, ExecutionPhase.FAILED, ExecutionPhase.FAILED_ITERATION_LIMIT}:
                    # Do not put terminal tasks back in the pool
                    return
            
            await sim.run(stop_event)
            
            # Put it back if the simulator finished without a terminal state
            await task_pool.put(t_id)
        except Exception as e:
            logger.error(f"Flight wrapper error: {e}")
        finally:
            task_pool.task_done()

    logger.info(f"Starting stage: Initial Limit={concurrency_controller.limit}, Duration={duration_s}s, TaskPoolSize={len(task_ids)}")
    
    while time.time() - start_time < duration_s and not stop_event.is_set():
        # DYNAMIC CONCURRENCY CHECK
        # Only launch if we are under the current governor limit
        if len(active_flights) < concurrency_controller.limit:
            task = asyncio.create_task(flight_wrapper())
            active_flights.append(task)
        
        # Clean up finished tasks
        active_flights = [t for t in active_flights if not t.done()]
        
        # Throttle launch rate slightly to prevent event loop spike
        await asyncio.sleep(0.05)

    # Wait for current flights to finish or stop
    await asyncio.gather(*active_flights, return_exceptions=True)
