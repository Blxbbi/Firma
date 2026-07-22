import asyncio
import json
import logging
import os
import time
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Union, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)

class Telemetry:
    """
    SRE-Grade Telemetry Engine.
    """
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(Telemetry, cls).__new__(cls)
        return cls._instance

    def __init__(self, output_dir: str = "benchmarks/telemetry"):
        if hasattr(self, "_initialized"):
            return
        
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Global Counters
        self._counters: Dict[str, int] = {}
        
        # Global Gauges (Current state)
        self._gauges: Dict[str, float] = {}
        
        # Sliding Window Events (timestamp, event_name)
        self._events = deque(maxlen=20000)
        
        # Histograms
        self._histograms: Dict[str, deque] = {}
        self._histogram_max_size = 10000
        
        self._running = False
        self._flush_task: Optional[asyncio.Task] = None
        self._loop_monitor_task: Optional[asyncio.Task] = None
        
        self.enabled = os.getenv("FIRMA_TELEMETRY", "on").lower() == "on"
        self._initialized = True

    def reset(self):
        if not self.enabled: return
        self._counters.clear()
        self._events.clear()
        self._histograms.clear()
        logger.info("SRE Telemetry reset.")

    def set_gauge(self, name: str, value: float):
        if not self.enabled: return
        self._gauges[name] = value

    def get_gauge(self, name: str) -> float:
        return self._gauges.get(name, 0.0)

    def increment(self, name: str, value: int = 1):
        if not self.enabled: return
        self._counters[name] = self._counters.get(name, 0) + value
        # Log event for sliding window
        for _ in range(value):
            self._events.append((time.time(), name))

    def increment_by(self, name: str, value: int = 1):
        """Alias for increment for compatibility."""
        self.increment(name, value)

    def observe(self, name: str, value: Union[int, float]):
        if not self.enabled: return
        if name not in self._histograms:
            self._histograms[name] = deque(maxlen=self._histogram_max_size)
        self._histograms[name].append(value)

    def get_window_stats(self, window_seconds: float = 5.0) -> Dict[str, float]:
        """Calculates rates for the last N seconds."""
        if not self.enabled: return {}
        
        now = time.time()
        window_start = now - window_seconds
        
        # Filter events in window
        events_in_window = [e for e in self._events if e[0] >= window_start]
        
        # Internal Engine Metrics
        attempts = sum(1 for e in events_in_window if e[1] == "cas_attempts")
        conflicts = sum(1 for e in events_in_window if e[1] == "cas_conflicts")
        retries = sum(1 for e in events_in_window if e[1] == "cas_successful_retries")
        conflict_rate = (conflicts / attempts) if attempts > 0 else 0.0
        
        # LLM External Metrics
        llm_reqs = sum(1 for e in events_in_window if e[1] == "llm_request")
        llm_errs = sum(1 for e in events_in_window if e[1] == "llm_error")
        llm_error_rate = (llm_errs / llm_reqs) if llm_reqs > 0 else 0.0
        
        # Latency Calculation (p50, p95)
        def get_percentile(name: str, p: float) -> float:
            samples = list(self._histograms.get(name, []))
            if not samples: return 0.0
            sorted_vals = sorted(samples)
            return sorted_vals[int(len(sorted_vals) * p)]

        p95_lag = get_percentile("loop_lag_ns", 0.95)
        llm_p50 = get_percentile("llm_latency_ms", 0.50)
        llm_p95 = get_percentile("llm_latency_ms", 0.95)
            
        return {
            "cas_conflict_rate": conflict_rate,
            "cas_attempts": attempts,
            "cas_conflicts": conflicts,
            "loop_lag_p95": p95_lag,
            "avg_retry_depth": retries / (attempts if attempts > 0 else 1),
            "llm_error_rate": llm_error_rate,
            "llm_latency_p50": llm_p50,
            "llm_latency_p95": llm_p95,
            "llm_inflight": self.get_gauge("llm_inflight")
        }

    def snapshot(self) -> Dict[str, Any]:
        if not self.enabled: return {}
        snapshot = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "counters": self._counters.copy(),
            "gauges": self._gauges.copy(),
            "histograms": {}
        }
        for name, samples in self._histograms.items():
            if not samples: continue
            vals = list(samples)
            snapshot["histograms"][name] = {
                "count": len(vals), "min": min(vals), "max": max(vals), "avg": sum(vals) / len(vals)
            }
        return snapshot

    async def start(self):
        if not self.enabled: return
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())
        self._loop_monitor_task = asyncio.create_task(self._run_loop_monitor())
        logger.info(f"SRE Telemetry started. Output directory: {self.output_dir}")

    async def stop(self):
        self._running = False
        if self._flush_task: await self._flush_task
        if self._loop_monitor_task: self._loop_monitor_task.cancel()
        await self.flush_to_disk()

    async def _flush_loop(self):
        while self._running:
            try:
                await asyncio.sleep(5.0)
                await self.flush_to_disk()
            except Exception as e:
                logger.error(f"Telemetry flush error: {e}")

    async def flush_to_disk(self):
        if not self.enabled: return
        timestamp = int(time.time())
        filename = self.output_dir / f"telemetry_{timestamp}.jsonl"
        with open(filename, "w") as f:
            f.write(json.dumps({"type": "counter_snapshot", "data": self._counters.copy()}) + "\n")
            for name, samples in self._histograms.items():
                current_samples = list(samples)
                self._histograms[name].clear()
                for s in current_samples:
                    f.write(json.dumps({"type": "sample", "metric": name, "value": s}) + "\n")

    async def _run_loop_monitor(self):
        interval_ns = 1_000_000_000
        while self._running:
            t0 = time.perf_counter_ns()
            await asyncio.sleep(1)
            t1 = time.perf_counter_ns()
            lag = (t1 - t0) - interval_ns
            self.observe("loop_lag_ns", lag)

telemetry = Telemetry()
