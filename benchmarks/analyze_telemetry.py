import json
import os
from collections import defaultdict
import numpy as np
from pathlib import Path

def analyze_telemetry(telemetry_dir):
    metrics = defaultdict(list)
    counters = defaultdict(int)
    
    files = sorted(Path(telemetry_dir).glob("*.jsonl"))
    for f_path in files:
        with open(f_path, "r") as f:
            for line in f:
                data = json.loads(line)
                if data["type"] == "sample":
                    metrics[data["metric"]].append(data["value"])
                elif data["type"] == "counter_snapshot":
                    for k, v in data["data"].items():
                        counters[k] += v

    results = {}
    for name, values in metrics.items():
        results[name] = {
            "count": len(values),
            "p50": float(np.percentile(values, 50)),
            "p95": float(np.percentile(values, 95)),
            "p99": float(np.percentile(values, 99)),
            "avg": float(np.mean(values)),
            "max": float(np.max(values))
        }
    
    return results, counters

if __name__ == "__main__":
    import sys
    dir_path = sys.argv[1]
    res, cnt = analyze_telemetry(dir_path)
    print("--- HISTOGRAMS ---")
    print(json.dumps(res, indent=2))
    print("\n--- COUNTERS ---")
    print(json.dumps(cnt, indent=2))
