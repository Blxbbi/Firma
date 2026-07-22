import asyncio
import logging
import os
import time
from engine.services.telemetry import telemetry

logger = logging.getLogger("engine.concurrency")

# --- Governor v2 Constants ---
API_ERROR_VETO = 0.05        # 5% Error → sofortige Reduktion
API_ERROR_CRITICAL = 0.10    # 10% → aggressivere Reduktion
LATENCY_HOLD_P95_MS = 1500   # p95 über 1.5s → kein Wachstum
CAS_DECREASE_THRESHOLD = 0.5
CAS_INCREASE_THRESHOLD = 0.3
LOOP_LAG_THRESHOLD_MS = 100

class ConcurrencyController:
    """
    Manages the dynamic limit of active tasks using AIMD (Additive Increase, Multiplicative Decrease).
    Includes expansion blocking to prevent oscillation during recovery.
    """
    def __init__(self, min_limit: int = None, max_limit: int = None):
        # Default limits based on hardware if not provided
        self.min_limit = min_limit or os.cpu_count() or 4
        self.max_limit = max_limit or (os.cpu_count() * 2 if os.cpu_count() else 8)
        self.current_limit = self.min_limit
        self._expansion_block_until = 0
        
        logger.info(f"ConcurrencyController initialized: min={self.min_limit}, max={self.max_limit}, start={self.current_limit}")

    def increase(self, additive_step: int = 1):
        """Additive increase: limit + step"""
        if self.current_limit < self.max_limit:
            self.current_limit = min(self.current_limit + additive_step, self.max_limit)
            logger.debug(f"Governor: Increasing concurrency to {self.current_limit}")

    def decrease(self, multiplicative_factor: float = 0.8):
        """Multiplicative decrease: limit * factor"""
        new_limit = int(self.current_limit * multiplicative_factor)
        self.current_limit = max(new_limit, self.min_limit)
        logger.debug(f"Governor: Decreasing concurrency to {self.current_limit}")

    def block_expansion(self, cooldown_seconds: float):
        """Prevents increase() from working for a set duration."""
        self._expansion_block_until = time.time() + cooldown_seconds
        logger.info(f"Governor: Expansion blocked for {cooldown_seconds}s")

    def expansion_blocked(self) -> bool:
        """Check if the expansion cooldown is still active."""
        return time.time() < self._expansion_block_until

    @property
    def limit(self) -> int:
        return self.current_limit

class AdaptiveConcurrencyGovernor:
    """
    Background task that monitors telemetry and adjusts the ConcurrencyController.
    Implements Governor v2: External Veto -> Pressure Hold -> Internal Tune.
    """
    def __init__(self, controller: ConcurrencyController, interval: float = 5.0):
        self.controller = controller
        self.interval = interval
        self._running = False
        self._task = None

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Adaptive Concurrency Governor v2 started.")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()

    async def _run_loop(self):
        while self._running:
            try:
                # Get sliding window stats from telemetry
                stats = telemetry.get_window_stats(window_seconds=self.interval)
                
                # Metrics mapping
                api_error = stats.get("llm_error_rate", 0.0)
                # Assume llm_latency_p95 is in nanoseconds or ms. 
                # Telemetry usually stores ns. Let's convert to ms.
                latency_p95_raw = stats.get("llm_latency_p95", 0.0)
                latency_p95_ms = latency_p95_raw / 1e6 if latency_p95_raw > 1000 else latency_p95_raw
                
                conflict_rate = stats.get("cas_conflict_rate", 0.0)
                retry_depth = stats.get("avg_retry_depth", 0.0)
                # Loop lag in ns
                lag_p95_ns = stats.get("loop_lag_p95", 0.0)
                lag_p95_ms = lag_p95_ns / 1e6

                logger.info(
                    f"Governor Check: api_err={api_error:.2%}, lat_p95={latency_p95_ms:.2f}ms, "
                    f"conflict={conflict_rate:.2%}, lag={lag_p95_ms:.2f}ms, "
                    f"limit={self.controller.limit}"
                )

                decision = "HOLD_STABLE"

                # -----------------------------
                # 1️⃣ HARD EXTERNAL VETO
                # -----------------------------
                if api_error >= API_ERROR_CRITICAL:
                    self.controller.decrease(multiplicative_factor=0.6)
                    self.controller.block_expansion(cooldown_seconds=10)
                    decision = "VETO_CRITICAL_API"
                elif api_error >= API_ERROR_VETO:
                    self.controller.decrease(multiplicative_factor=0.8)
                    self.controller.block_expansion(cooldown_seconds=5)
                    decision = "VETO_API"

                # -----------------------------
                # 2️⃣ PRESSURE HOLD ZONE
                # -----------------------------
                elif latency_p95_ms >= LATENCY_HOLD_P95_MS:
                    # hold() is implicit (no increase, no decrease)
                    decision = "HOLD_LATENCY"

                # -----------------------------
                # 3️⃣ INTERNAL INTERFERENCE
                # -----------------------------
                elif conflict_rate >= CAS_DECREASE_THRESHOLD or retry_depth > 3:
                    self.controller.decrease(multiplicative_factor=0.8)
                    decision = "DECREASE_CAS"

                # -----------------------------
                # 4️⃣ HEALTHY GROWTH
                # -----------------------------
                elif (
                    conflict_rate < CAS_INCREASE_THRESHOLD 
                    and lag_p95_ms < LOOP_LAG_THRESHOLD_MS 
                    and not self.controller.expansion_blocked()
                ):
                    self.controller.increase(additive_step=1)
                    decision = "INCREASE"

                logger.info(f"Governor Decision: {decision} -> New Limit: {self.controller.limit}")
                
            except Exception as e:
                logger.error(f"Governor loop error: {e}")
            
            await asyncio.sleep(self.interval)

# Global singleton for the engine
concurrency_controller = ConcurrencyController()
governor = AdaptiveConcurrencyGovernor(concurrency_controller)
