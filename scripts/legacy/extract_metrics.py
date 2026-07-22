
import json
import os
from pathlib import Path

def analyze_telemetry():
    telemetry_dir = Path("benchmarks/telemetry")
    files = sorted(telemetry_dir.glob("telemetry_*.jsonl"), key=lambda x: x.stem.split("_")[1])
    
    stages_data = []
    current_stage_snapshots = []
    
    for f in files:
        with open(f, "r") as file:
            for line in file:
                data = json.loads(line)
                if data["type"] == "counter_snapshot":
                    current_val = data["data"].get("cas_attempts", 0)
                    
                    # Detect reset: if current attempts < last recorded attempts, a new stage started
                    if current_stage_snapshots and current_val < current_stage_snapshots[-1].get("cas_attempts", 0):
                        # Save the last snapshot of the previous stage
                        stages_data.append(current_stage_snapshots[-1])
                        current_stage_snapshots = []
                    
                    current_stage_snapshots.append(data["data"])
    
    # Add the last stage
    if current_stage_snapshots:
        stages_data.append(current_stage_snapshots[-1])
    
    return stages_data

def main():
    stages_results = analyze_telemetry()
    
    if not stages_results:
        print("No telemetry data found.")
        return

    # We expect Baseline, L10, L20, L40, L60 (5 stages)
    stage_labels = ["Baseline", "L10", "L20", "L40", "L60"]
    
    print(f"{'Stage':<12} | {'Attempts':<10} | {'Success':<10} | {'Conflicts':<10} | {'Retries':<10} | {'Efficiency':<12}")
    print("-" * 75)
    
    for i, data in enumerate(stages_results):
        label = stage_labels[i] if i < len(stage_labels) else f"S{i}"
        att = data.get("cas_attempts", 0)
        suc = data.get("cas_success", 0)
        con = data.get("cas_conflicts", 0)
        ret = data.get("cas_successful_retries", 0)
        eff = (suc / att * 100) if att > 0 else 0
        
        print(f"{label:<12} | {att:<10} | {suc:<10} | {con:<10} | {ret:<10} | {eff:>11.2f}%")

if __name__ == "__main__":
    main()
