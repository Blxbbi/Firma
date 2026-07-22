
import json
from pathlib import Path
from datetime import datetime, timezone

def analyze_run_telemetry(run_start_iso, stages):
    telemetry_dir = Path("benchmarks/telemetry")
    files = sorted(telemetry_dir.glob("telemetry_*.jsonl"), key=lambda x: x.stem.split("_")[1])
    
    # Convert ISO to unix timestamp
    start_ts = int(datetime.fromisoformat(run_start_iso).timestamp())
    
    # Parse stages into timestamps
    stage_windows = []
    prev_ts = start_ts
    for stage, end_iso in stages.items():
        end_ts = int(datetime.fromisoformat(end_iso).timestamp())
        stage_windows.append((stage, prev_ts, end_ts))
        prev_ts = end_ts
        
    results = {}
    
    for stage, start, end in stage_windows:
        max_counters = {}
        found = False
        
        for f in files:
            file_ts = int(f.stem.split("_")[1])
            if start <= file_ts <= end:
                with open(f, "r") as file:
                    for line in file:
                        data = json.loads(line)
                        if data["type"] == "counter_snapshot":
                            found = True
                            for k, v in data["data"].items():
                                max_counters[k] = max(max_counters.get(k, 0), v)
        
        if found:
            results[stage] = max_counters
        else:
            results[stage] = None
            
    return results

def main():
    run_start = "2026-07-01T20:54:18+00:00"
    stages = {
        "L10": "2026-07-01T20:55:41+00:00",
        "L20": "2026-07-01T20:56:52+00:00",
        "L40": "2026-07-01T20:58:03+00:00",
        "L60": "2026-07-01T20:59:14+00:00",
    }
    
    res = analyze_run_telemetry(run_start, stages)
    
    print(f"{'Stage':<10} | {'Attempts':<10} | {'Success':<10} | {'Conflicts':<10} | {'Retries':<10} | {'Efficiency':<12}")
    print("-" * 75)
    
    for stage, data in res.items():
        if data:
            att = data.get("cas_attempts", 0)
            suc = data.get("cas_success", 0)
            con = data.get("cas_conflicts", 0)
            ret = data.get("cas_successful_retries", 0)
            eff = (suc / att * 100) if att > 0 else 0
            print(f"{stage:<10} | {att:<10} | {suc:<10} | {con:<10} | {ret:<10} | {eff:>11.2f}%")
        else:
            print(f"{stage:<10} | No data found in time window")

if __name__ == "__main__":
    main()
