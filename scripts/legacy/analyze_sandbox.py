
import json
from pathlib import Path

def analyze_sandbox_profile():
    telemetry_dir = Path("benchmarks/telemetry")
    files = sorted(telemetry_dir.glob("telemetry_*.jsonl"), key=lambda x: x.stem.split("_")[1])
    
    startup_samples = []
    exec_samples = []
    
    for f in files:
        with open(f, "r") as file:
            for line in file:
                data = json.loads(line)
                if data["type"] == "sample":
                    if data["metric"] == "sandbox_startup_latency_ns":
                        startup_samples.append(data["value"])
                    elif data["metric"] == "sandbox_exec_latency_ns":
                        exec_samples.append(data["value"])
    
    if not exec_samples:
        print("No sandbox telemetry found.")
        return

    avg_startup = (sum(startup_samples) / len(startup_samples)) / 1e6 if startup_samples else 0
    avg_exec = (sum(exec_samples) / len(exec_samples)) / 1e6
    
    print(f"--- Sandbox Time Profile ---")
    print(f"Avg Startup (Spawn): {avg_startup:>10.2f} ms")
    print(f"Avg Total Exec:     {avg_exec:>10.2f} ms")
    print(f"Startup % of Total: {(avg_startup/avg_exec*100 if avg_exec > 0 else 0):>10.2f}%")

if __name__ == "__main__":
    analyze_sandbox_profile()
