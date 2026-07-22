pimport matplotlib.pyplot as plt
from pathlib import Path
from typing import List, Dict, Any
from benchmarks.statistics import MetricStats

class ReportGenerator:
    """
    Generates a formal industrial markdown report and corresponding graphs.
    """
    def __init__(self, run_dir: Path, profile_name: str):
        self.run_dir = run_dir
        self.profile_name = profile_name
        self.plots_dir = run_dir / "plots"
        self.plots_dir.mkdir(parents=True, exist_ok=True)

    def generate_graphs(self, stage_data: List[Dict[str, Any]]):
        """
        Creates the 5 mandatory scaling graphs.
        stage_data: list of {concurrency, stats: {metric_name: MetricStats}}
        """
        concurrencies = [s["concurrency"] for s in stage_data]
        metrics_to_plot = {
            "transition_latency_ns": "p99",
            "cas_conflict_rate": "value",
            "db_commit_latency_ns": "p95",
            "loop_lag_ns": "p95",
            "cpu_percent": "mean"
        }

        for metric_name, stat_type in metrics_to_plot.items():
            vals = []
            for s in stage_data:
                m = s["stats"].get(metric_name)
                if m is None:
                    vals.append(None)
                    continue
                
                if stat_type == "value":
                    vals.append(m if isinstance(m, (int, float)) else 0)
                elif hasattr(m, stat_type):
                    vals.append(getattr(m, stat_type))
                else:
                    vals.append(None)

            plt.figure(figsize=(10, 6))
            plt.plot(concurrencies, vals, marker='o', linestyle='-', color='b')
            plt.title(f"{self.profile_name} - {metric_name} ({stat_type})")
            plt.xlabel("Concurrency")
            plt.ylabel("Value")
            plt.grid(True)
            plt.savefig(self.plots_dir / f"{metric_name}.png")
            plt.close()

    def write_markdown(self, report_data: Dict[str, Any]):
        """Writes the final formal report to markdown."""
        output_path = self.run_dir / f"{self.profile_name}_report.md"
        
        with open(output_path, "w") as f:
            f.write(f"# Phase 5 Benchmark Report - {self.profile_name}\n\n")
            
            f.write("## 1. Environment\n")
            meta = report_data["metadata"]
            f.write(f"- **Hardware:** {meta.get('hardware', 'Unknown')}\n")
            f.write(f"- **Profile:** {self.profile_name}\n")
            f.write(f"- **Seed:** {meta.get('seed', 'N/A')}\n\n")
            
            f.write("## 2. Baseline Metrics\n")
            baseline = report_data["baseline"]
            f.write("| Metric | p50 | p95 | p99 |\n")
            f.write("|---|---|---|---|\n")
            for m, s in baseline.items():
                if hasattr(s, 'p50'):
                    f.write(f"| {m} | {s.p50:.2f} | {s.p95:.2f} | {s.p99:.2f} |\n")
            f.write("\n")
            
            f.write("## 3. Scaling Results\n")
            f.write("| Concurrency | Transition p99 | CAS Rate | DB p95 | Loop Lag p95 |\n")
            f.write("|---|---|---|---|---|\n")
            for stage in report_data["stages"]:
                s = stage["stats"]
                t = s.get("transition_latency_ns")
                cas = s.get("cas_conflict_rate", 0)
                db = s.get("db_commit_latency_ns")
                loop = s.get("loop_lag_ns")
                
                f.write(f"| {stage['concurrency']} | {t.p99 if t else 'N/A'} | {cas:.2%} | {db.p95 if db else 'N/A'} | {loop.p95 if loop else 'N/A'} |\n")
            f.write("\n")
            
            f.write("## 4. Identified Tipping Point\n")
            tp = report_data["tipping_point"]
            if tp:
                f.write(f"**Tipping Point identified at L{tp.concurrency}**\n\n")
                f.write(f"- **Primary Bottleneck:** {tp.primary_bottleneck}\n")
                f.write(f"- **Secondary Signals:** {', '.join(tp.secondary_signals)}\n")
            else:
                f.write("No tipping point identified within tested range.\n")
            f.write("\n")
            
            f.write("## 5. Engineering Recommendation\n")
            f.write(report_data["recommendation"])

        return output_path
