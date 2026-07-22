import os
from dataclasses import dataclass
from pathlib import Path

@dataclass
class BenchmarkConfig:
    output_dir: Path = Path("benchmarks/results")
    telemetry_dir: Path = Path("benchmarks/telemetry")
    db_url: str = "sqlite+aiosqlite:///firma_benchmark.db"
    artifact_root: Path = Path("artifact_store/benchmarks")
    
    # Default timings
    default_duration: int = 300
    default_warmup: int = 60
    
    # Safety thresholds
    max_loop_lag_ns: int = 500_000_000  # 500ms
    max_cas_conflict_rate: float = 0.40
    max_rss_percent: float = 90.0

config = BenchmarkConfig()
