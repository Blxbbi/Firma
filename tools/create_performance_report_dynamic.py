#!/usr/bin/env python3
"""Generate performance report for a specific run."""
import json, os, re
from datetime import datetime

def parse_time(t):
    return datetime.strptime(t, "%H:%M:%S")

def time_diff(start, end):
    s = parse_time(start)
    e = parse_time(end)
    return int((e - s).total_seconds())

run_id = "b1703a8e-6ba0-41b9-bb98-171e4a6b6aed"
run_dir = f"archive/runs/{run_id}"
log_path = f"{run_dir}/run.log"

# Parse run.log
events = []
with open(log_path, "r", encoding="utf-8") as f:
    for line in f:
        # Spawn events
        m = re.search(r"(\d{2}:\d{2}:\d{2}).*spawned (\w+) worker for (\S+)", line)
        if m:
            events.append({"time": m.group(1), "role": m.group(2), "task_id": m.group(3), "type": "spawn"})
        # Submission events
        m = re.search(r"(\d{2}:\d{2}:\d{2}).*(?:submitted|EVENT].*?)(\w+) for Task (\S+)", line)
        if m:
            events.append({"time": m.group(1), "event": m.group(2), "task_id": m.group(3), "type": "submit"})
        # Run start/end
        m = re.search(r"(\d{2}:\d{2}:\d{2}).*Execution started for run", line)
        if m:
            events.append({"time": m.group(1), "event": "RUN_START", "type": "meta"})
        m = re.search(r"(\d{2}:\d{2}:\d{2}).*Run .* has reached terminal state: (\w+)", line)
        if m:
            events.append({"time": m.group(1), "event": "RUN_END", "status": m.group(2), "type": "meta"})

# Build task timeline
task_timeline = {}
for e in events:
    if "task_id" not in e:
        continue
    tid = e["task_id"]
    if tid not in task_timeline:
        task_timeline[tid] = {"task_id": tid, "role": e.get("role", "?"), "spawn": None, "events": []}
    if e["type"] == "spawn":
        task_timeline[tid]["spawn"] = e["time"]
        task_timeline[tid]["role"] = e["role"]
    elif e["type"] == "submit":
        task_timeline[tid]["events"].append({"time": e["time"], "event": e["event"]})

# Calculate durations
rows = []
for tid, data in task_timeline.items():
    spawn = data["spawn"]
    role = data["role"]
    for i, ev in enumerate(data["events"]):
        if spawn:
            duration = time_diff(spawn, ev["time"])
            rows.append({
                "task_id": tid,
                "role": role,
                "event": ev["event"],
                "start": spawn,
                "end": ev["time"],
                "duration": duration,
            })

# Run timing
run_start = next((e["time"] for e in events if e.get("event") == "RUN_START"), "?")
run_end = next((e["time"] for e in events if e.get("event") == "RUN_END"), "?")
run_status = next((e.get("status", "?") for e in events if e.get("event") == "RUN_END"), "?")

# Count events
event_counts = {}
for r in rows:
    key = f"{r['role']}:{r['event']}"
    event_counts[key] = event_counts.get(key, 0) + 1

# Generate report
lines = []
lines.append("=" * 80)
lines.append("E2E RUN PERFORMANCE REPORT")
lines.append("=" * 80)
lines.append("")
lines.append(f"Run ID:       {run_id}")
lines.append(f"Started:      {run_start}")
lines.append(f"Finished:     {run_end}")
lines.append(f"Status:       {run_status}")
lines.append(f"Total Tasks:  {len(task_timeline)}")
lines.append("")

lines.append("[TASK TIMELINE]")
lines.append("-" * 80)
lines.append(f"{'Task ID':<15} {'Role':<12} {'Event':<20} {'Start':>8} {'End':>8} {'Dur':>6}")
lines.append("-" * 80)
for r in rows:
    lines.append(f"{r['task_id']:<15} {r['role']:<12} {r['event']:<20} {r['start']:>8} {r['end']:>8} {r['duration']:>5}s")
lines.append("")

lines.append("[EVENT SUMMARY]")
lines.append("-" * 80)
for key, count in sorted(event_counts.items()):
    lines.append(f"  {key:<40} {count:>3}x")
lines.append("")

# Artifact sizes
artifacts = []
for root, dirs, files in os.walk(f"data/artifacts/{run_id}"):
    for f in files:
        path = os.path.join(root, f)
        size = os.path.getsize(path)
        rel = os.path.relpath(path, f"data/artifacts/{run_id}")
        artifacts.append((rel, size))

lines.append("[ARTIFACTS]")
lines.append("-" * 80)
total_bytes = 0
for path, size in sorted(artifacts):
    lines.append(f"  {path:<60} {size:>8,} bytes")
    total_bytes += size
lines.append("-" * 80)
lines.append(f"  {'TOTAL':<60} {total_bytes:>8,} bytes")
lines.append("")

# Worker logs check
lines.append("[WORKER LOGS]")
lines.append("-" * 80)
for tid in sorted(task_timeline.keys()):
    log_path_task = f"pimesh/coding-crew/.pi/work/{run_id}/{tid}/worker.log"
    if os.path.exists(log_path_task):
        size = os.path.getsize(log_path_task)
        lines.append(f"  {tid:<15} {size:>8,} bytes")
    else:
        lines.append(f"  {tid:<15} {'MISSING':>8}")
lines.append("")

lines.append("[KEY FINDINGS]")
lines.append("-" * 80)
findings = []
for r in rows:
    if r["duration"] > 120:
        findings.append(f"- {r['role']} {r['task_id']}: {r['event']} after {r['duration']}s (SLOW)")
    if r["event"] == "REVIEW_APPROVED":
        findings.append(f"- {r['role']} {r['task_id']}: APPROVED (reviewer fix validated)")
    if r["event"] == "CODE_SUBMITTED":
        findings.append(f"- {r['role']} {r['task_id']}: CODE_SUBMITTED")
if not findings:
    findings.append("- All tasks completed within normal time")
for f in findings:
    lines.append(f)
lines.append("")
lines.append("=" * 80)

report = "\n".join(lines)
print(report)

with open(f"deliverables/e2e_reviewer_fix_performance_report.txt", "w", encoding="utf-8") as f:
    f.write(report)
print(f"\nReport saved to: deliverables/e2e_reviewer_fix_performance_report.txt")
