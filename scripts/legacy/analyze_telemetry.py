
import json
import os
from pathlib import Path
from datetime import datetime

def parse_telemetry():
    telemetry_dir = Path("benchmarks/telemetry")
    files = sorted(telemetry_dir.glob("telemetry_*.jsonl"))
    
    all_snapshots = []
    
    for f in files:
        with open(f, "r") as file:
            for line in file:
                data = json.loads(line)
                if data["type"] == "counter_snapshot":
                    timestamp = int(f.stem.split("_")[1])
                    all_snapshots.append({
                        "timestamp": timestamp,
                        "data": data["data"]
                    })
    
    return all_snapshots

def main():
    snapshots = parse_telemetry()
    if not snapshots:
        print("No telemetry found.")
        return

    # The run 20260701T205418_io_efficiency_curve_v1
    # L10: 20:55:41 -> 1782942941
    # L20: 20:56:52 -> 1782943012
    # L40: 20:58:03 -> 1782943083
    # L60: 20:59:14 -> 1782943154
    
    # Note: I will use the timestamps from the snapshot files for mapping
    stages = {
        "L10": 1782942941,
        "L20": 1782943012,
        "L40": 1782943083,
        "L60": 1782943154,
    }
    
    print(f"{'Stage':<10} | {'Attempts':<10} | {'Success':<10} | {'Conflicts':<10} | {'Retries':<10} | {'Efficiency':<10}")
    print("-" * 70)
    
    for stage, ts in stages.items():
        # Find the snapshot closest to (but before) the stage end timestamp
        best_snapshot = None
        for s in snapshots:
            if s["timestamp"] <= ts:
                best_snapshot = s
            else:
                break
        
        if best_snapshot:
            d = best_snapshot["data"]
            att = d.get("cas_attempts", 0)
            suc = d.get("cas_success", 0)
            con = d.get("cas_conflicts", 0)
            ret = d.get("cas_successful_retries", 0)
            eff = (suc / att * 100) if att > 0 else 0
            print(f"{stage:<10} | {att:<10} | {suc:<10} | {con:<10} | {ret:<10} | {eff:>9.2f}%")
        else:
            print(f"{stage:<10} | No data found")

if __name__ == "__main__":
    main()
