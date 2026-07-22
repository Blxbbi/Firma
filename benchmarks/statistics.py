import numpy as np
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

@dataclass
class MetricStats:
    count: int
    mean: float
    p50: float
    p95: float
    p99: float
    max: float
    stddev: float

class StatisticsEngine:
    """
    Formal statistical engine for benchmark data analysis.
    Operates on raw samples to ensure precision.
    """
    
    @staticmethod
    def compute_stats(samples: List[float]) -> Optional[MetricStats]:
        if not samples:
            return None
            
        arr = np.array(samples)
        return MetricStats(
            count=len(arr),
            mean=float(np.mean(arr)),
            p50=float(np.percentile(arr, 50)),
            p95=float(np.percentile(arr, 95)),
            p99=float(np.percentile(arr, 99)),
            max=float(np.max(arr)),
            stddev=float(np.std(arr))
        )

    @staticmethod
    def compute_weighted_percentile(buckets: Dict[float, int], percentile: float) -> float:
        """
        Reconstructs percentiles from histogram buckets if raw samples are unavailable.
        """
        sorted_buckets = sorted(buckets.items())
        total_count = sum(buckets.values())
        if total_count == 0:
            return 0.0
            
        target = (percentile / 100.0) * total_count
        current_count = 0
        for val, count in sorted_buckets:
            current_count += count
            if current_count >= target:
                return val
        return sorted_buckets[-1][0] if sorted_buckets else 0.0
