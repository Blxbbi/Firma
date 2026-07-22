import asyncio
import logging
import time
from typing import List, Dict
from engine.services.sandbox import SandboxExecutor, ExecutionResult
from engine.services.telemetry import telemetry

logger = logging.getLogger(__name__)

class DummySandbox(SandboxExecutor):
    """
    A zero-overhead sandbox for pure kernel characterization.
    Simulates execution without spawning processes.
    """
    async def run(self, files: List[Dict[str, str]], command: str, timeout: float) -> ExecutionResult:
        t0 = time.perf_counter_ns()
        
        # Simulate a tiny bit of overhead (e.g. 1ms) to avoid 0ns measurements
        # which can be misleading in async loops.
        await asyncio.sleep(0.001)
        
        # We return a failure (exit 2) to keep the FSM cycling 
        # and maintain steady-state load.
        res = ExecutionResult(
            exit_code=2, 
            stdout="Dummy success", 
            stderr="Dummy failure (forced for load)", 
            timed_out=False
        )
        
        telemetry.observe("sandbox_exec_latency_ns", time.perf_counter_ns() - t0)
        return res
