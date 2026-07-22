from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from benchmarks.statistics import MetricStats

@dataclass
class TippingPoint:
    concurrency: int
    primary_bottleneck: str
    secondary_signals: List[str]
    is_critical: bool

class TippingPointDetector:
    """
    Implements the formal Tipping Point Algorithm for Firma.
    """
    
    def __init__(self, baseline_stats: Dict[str, MetricStats]):
        self.baseline = baseline_stats

    def evaluate_stage(self, concurrency: int, stats: Dict[str, MetricStats]) -> Optional[TippingPoint]:
        # 1. Tail Explosion Check
        trans = stats.get("transition_latency_ns")
        if trans:
            tail_ratio = trans.p99 / trans.p50 if trans.p50 > 0 else 0
            if tail_ratio > 3:
                return TippingPoint(
                    concurrency=concurrency,
                    primary_bottleneck="Tail Explosion",
                    secondary_signals=[f"Tail Ratio: {tail_ratio:.2f}"],
                    is_critical=True
                )

        # 2. CAS Saturation Check
        # Note: CAS rate is usually a counter, not a latency
        # We expect the evaluator to pass the rates in the stats dict
        cas_rate = stats.get("cas_conflict_rate", 0.0)
        if isinstance(cas_rate, float) and cas_rate > 0.15:
            return TippingPoint(
                concurrency=concurrency,
                primary_bottleneck="CAS Saturation",
                secondary_signals=[f"Conflict Rate: {cas_rate*100:.2f}%"],
                is_critical=True
            )

        # 3. Storage Kipppunkt
        db_commit = stats.get("db_commit_latency_ns")
        if db_commit:
            baseline_db = self.baseline.get("db_commit_latency_ns")
            if baseline_db and db_commit.p99 > 5 * baseline_db.p99:
                return TippingPoint(
                    concurrency=concurrency,
                    primary_bottleneck="Storage Bottleneck",
                    secondary_signals=[f"P99 > 5x Baseline ({db_commit.p99/baseline_db.p99:.2f}x)"],
                    is_critical=True
                )

        # 4. Loop Sättigung
        loop_lag = stats.get("loop_lag_ns")
        if loop_lag and loop_lag.p95 > 100_000_000: # 100ms
            return TippingPoint(
                concurrency=concurrency,
                primary_bottleneck="Async Saturation",
                secondary_signals=[f"Loop Lag P95: {loop_lag.p95/1e6:.2f}ms"],
                is_critical=True
            )

        return None

    def classify_bottleneck(self, stats: Dict[str, Any]) -> str:
        """
        Final classification based on dominant metrics at the tipping point.
        """
        # Priority: Loop -> Storage -> CAS -> Compute
        if stats.get("loop_lag_p95", 0) > 100_000_000:
            return "Async Saturation"
        if stats.get("db_commit_p95", 0) > 300_000_000: # Example 300ms
            return "Storage"
        if stats.get("cas_conflict_rate", 0) > 0.15:
            return "FSM/CAS"
        
        return "Compute Bound"
