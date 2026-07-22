import argparse
import json
import logging
import os
from pathlib import Path
from typing import List, Dict, Any

import numpy as np
from benchmarks.statistics import StatisticsEngine, MetricStats
from benchmarks.tipping import TippingPointDetector
from benchmarks.report import ReportGenerator

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("benchmark.evaluator")

class Evaluator:
    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.stats_engine = StatisticsEngine()
        
    def load_run_data(self) -> Dict[str, Any]:
        """Parses all JSONL and snapshot files in the run directory."""
        # 1. Load metadata
        meta_path = self.run_dir / "metadata.json"
        metadata = {}
        if meta_path.exists():
            with open(meta_path, "r") as f:
                metadata = json.load(f)
        
        # 2. Parse Stages
        # We look for snapshot_{stage}.json
        stages = []
        # Sort snapshot files by the number in the filename
        snapshot_files = sorted(
            [f for f in self.run_dir.glob("snapshot_stage_*.json")],
            key=lambda x: int(x.stem.split("_")[-1])
        )
        
        for f_path in snapshot_files:
            with open(f_path, "r") as f:
                snap = json.load(f)
                concurrency = int(f_path.stem.split("_")[-1])
                
                # Process histogram summaries into MetricStats
                processed_stats = {}
                for m_name, m_data in snap.get("histograms", {}).items():
                    # Note: Since snapshots are summaries, we create a 'pseudo' MetricStats
                    # In a full raw-sample run, we'd read the JSONL files.
                    processed_stats[m_name] = MetricStats(
                        count=m_data["count"],
                        mean=m_data["avg"],
                        p50=m_data["avg"], # Simplification for summary data
                        p95=m_data["max"] * 0.9, # Rough approx if only avg/max provided
                        p99=m_data["max"],
                        max=m_data["max"],
                        stddev=0.0
                    )
                
                # Add counters
                counters = snap.get("counters", {})
                for c_name, c_val in counters.items():
                    processed_stats[c_name] = c_val
                
                stages.append({
                    "concurrency": concurrency,
                    "stats": processed_stats
                })
        
        # 3. Extract Baseline
        baseline_path = self.run_dir / "snapshot_baseline.json"
        baseline_stats = {}
        if baseline_path.exists():
            with open(baseline_path, "r") as f:
                base_snap = json.load(f)
                for m_name, m_data in base_snap.get("histograms", {}).items():
                    baseline_stats[m_name] = MetricStats(
                        count=m_data["count"],
                        mean=m_data["avg"],
                        p50=m_data["avg"],
                        p95=m_data["max"] * 0.9,
                        p99=m_data["max"],
                        max=m_data["max"],
                        stddev=0.0
                    )

        return {
            "metadata": metadata,
            "stages": stages,
            "baseline": baseline_stats
        }

    def analyze(self):
        data = self.load_run_data()
        if not data["stages"]:
            logger.error("No stage data found. Aborting.")
            return
            
        detector = TippingPointDetector(data["baseline"])
        
        tipping_point = None
        for stage in data["stages"]:
            tp = detector.evaluate_stage(stage["concurrency"], stage["stats"])
            if tp:
                tipping_point = tp
                break
        
        # Calculate Stability Index (simplified)
        # We use the last stage as the test point
        last_stage = data["stages"][-1]
        stability_index = self._calculate_stability(last_stage, data["baseline"])
        
        # Map tipping point to a recommendation
        recommendation = self._get_recommendation(tipping_point, stability_index)
        
        # Generate Report
        profile_name = data["metadata"].get("profile", "unknown")
        reporter = ReportGenerator(self.run_dir, profile_name)
        
        # Generate graphs (using raw data if available, otherwise simplified)
        reporter.generate_graphs(data["stages"])
        
        report_data = {
            "metadata": data["metadata"],
            "baseline": data["baseline"],
            "stages": data["stages"],
            "tipping_point": tipping_point,
            "recommendation": recommendation
        }
        
        report_path = reporter.write_markdown(report_data)
        logger.info(f"Evaluation complete. Report generated: {report_path}")
        
        return tipping_point, stability_index

    def _calculate_stability(self, stage, baseline) -> float:
        # Stability_Index = 1 / (Tail_Ratio * CAS_Rate * Overhead_Factor)
        trans = stage["stats"].get("transition_latency_ns")
        if not trans or not hasattr(trans, 'p50'):
            return 0.0
            
        tail_ratio = trans.p99 / trans.p50 if trans.p50 > 0 else 1.0
        cas_rate = stage["stats"].get("cas_conflict_rate", 0.01)
        
        baseline_trans = baseline.get("transition_latency_ns")
        overhead = (trans.p50 / baseline_trans.p50) if baseline_trans and baseline_trans.p50 > 0 else 1.0
        
        # Normalized Stability Index
        index = 1.0 / (max(1.0, tail_ratio) * max(1.0, cas_rate * 10) * max(1.0, overhead))
        return float(index)

    def _get_recommendation(self, tp, stability) -> str:
        if not tp:
            return "### ✅ PRODUCTION READY\nSystem scaled linearly across all tested ranges. No critical bottlenecks identified."
        
        if tp.primary_bottleneck == "Storage Bottleneck":
            return "### ⚠️ STORAGE LIMIT REACHED\nRecommendation: Migrate from SQLite to PostgreSQL (asyncpg) to handle higher write concurrency."
        elif tp.primary_bottleneck == "CAS Saturation":
            return "### ⚠️ FSM CONTENTION\nRecommendation: Reduce the granularity of state transitions or implement a more robust queuing mechanism."
        elif tp.primary_bottleneck == "Async Saturation":
            return "### ⚠️ EVENT LOOP STARVATION\nRecommendation: Audit critical paths for blocking I/O and offload heavy compute to worker threads."
        
        return f"### ⚠️ SYSTEM INSTABILITY\nBottleneck identified as {tp.primary_bottleneck}. Immediate architecture review required."

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=str, required=True)
    args = parser.parse_args()
    
    evaluator = Evaluator(Path(args.run))
    evaluator.analyze()
