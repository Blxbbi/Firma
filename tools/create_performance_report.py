#!/usr/bin/env python3
"""
Create performance report from run data.
Uses data already extracted from the run output.
"""
import json
from datetime import datetime

# Data extracted from the run output
run_data = {
    "run_id": "3e116b25-8146-4a45-bde8-c0e22517f21e",
    "prompt": "SaaS Onboarding Wizard",
    "started_at": "2026-07-30T11:19:43",
    "finished_at": "2026-07-30T11:39:41",
    "timeout": True,
    "timeout_seconds": 1200,
}

# Task timing data from run.log
tasks_timing = [
    {"task_id": "c770e6e5", "role": "RESEARCHER", "start": "11:19:43", "end": "11:19:44", "duration_seconds": 1, "status": "COMPLETE"},
    {"task_id": "65292f6a", "role": "PLANNER", "start": "11:19:44", "end": "11:21:00", "duration_seconds": 76, "status": "COMPLETE"},
    {"task_id": "task-1", "role": "CODER", "start": "11:21:01", "end": "11:31:01", "duration_seconds": 600, "status": "TIMEOUT"},
    {"task_id": "task-2", "role": "CODER", "start": "11:31:01", "end": "11:32:14", "duration_seconds": 73, "status": "COMPLETE"},
    {"task_id": "task-2", "role": "REVIEWER", "start": "11:32:15", "end": "11:34:10", "duration_seconds": 115, "status": "REVIEW_FAILURE"},
    {"task_id": "task-2", "role": "CODER", "start": "11:34:10", "end": "11:34:10", "duration_seconds": 0, "status": "RETRY_STARTED"},
    {"task_id": "task-2", "role": "CODER", "start": "11:38:35", "end": "11:38:35", "duration_seconds": 0, "status": "COMPLETE"},
    {"task_id": "task-3", "role": "CODER", "start": "11:32:15", "end": "11:38:34", "duration_seconds": 379, "status": "COMPLETE"},
    {"task_id": "task-3", "role": "REVIEWER", "start": "11:38:35", "end": "11:39:37", "duration_seconds": 62, "status": "REVIEW_APPROVED"},
]

# Token usage data from worker.log analysis
token_usage = [
    {"role": "RESEARCHER", "task_id": "c770e6e5", "turns": 13, "tools": 24, "input_tokens": 161867, "output_tokens": 16000, "cache_read": 215040},
    {"role": "PLANNER", "task_id": "65292f6a", "turns": 4, "tools": 8, "input_tokens": 41198, "output_tokens": 31089, "cache_read": 88320},
    {"task-1": "CODER", "task_id": "task-1", "turns": 0, "tools": 0, "input_tokens": 0, "output_tokens": 0, "cache_read": 0, "note": "TIMEOUT - no metrics"},
    {"role": "CODER", "task_id": "task-2", "turns": 8, "tools": 14, "input_tokens": 81678, "output_tokens": 36156, "cache_read": 226560},
    {"role": "CODER", "task_id": "task-3", "turns": 7, "tools": 12, "input_tokens": 97288, "output_tokens": 9136, "cache_read": 108288},
    {"role": "REVIEWER", "task_id": "task-2", "turns": 5, "tools": 8, "input_tokens": 53820, "output_tokens": 14154, "cache_read": 84096},
    {"role": "REVIEWER", "task_id": "task-3", "turns": 8, "tools": 12, "input_tokens": 142273, "output_tokens": 61892, "cache_read": 103680},
]

# Generate report
report = []
report.append("=" * 80)
report.append("RUN PERFORMANCE REPORT")
report.append("=" * 80)
report.append("")
report.append(f"Run ID: {run_data['run_id']}")
report.append(f"Prompt: {run_data['prompt']}")
report.append(f"Started: {run_data['started_at']}")
report.append(f"Finished: {run_data['finished_at']}")
report.append(f"Timeout: {'YES - after 1200s' if run_data['timeout'] else 'NO'}")
report.append("")

report.append("[TASK TIMING]")
report.append("-" * 80)
report.append(f"{'Task ID':<15} {'Role':<15} {'Start':>10} {'End':>10} {'Duration':>10} {'Status':<20}")
report.append("-" * 80)

for task in tasks_timing:
    report.append(f"{task['task_id']:<15} {task['role']:<15} {task['start']:>10} {task['end']:>10} {task['duration_seconds']:>9}s {task['status']:<20}")

report.append("")
report.append("[TOKEN USAGE PER AGENT]")
report.append("-" * 80)
report.append(f"{'Role':<15} {'Task ID':<15} {'Turns':>6} {'Tools':>6} {'Input':>10} {'Output':>10} {'CacheR':>10} {'Total':>12}")
report.append("-" * 80)

total_turns = 0
total_tools = 0
total_input = 0
total_output = 0
total_cache = 0

for m in token_usage:
    if 'note' in m:
        total = m.get('total_tokens') or (m.get('input_tokens', 0) + m.get('output_tokens', 0) + m.get('cache_read', 0))
        report.append(f"{m.get('role', '?'):<15} {m.get('task_id', '?'):<15} {m.get('turns', 0):>6} {m.get('tools', 0):>6} {m.get('input_tokens', 0):>10,} {m.get('output_tokens', 0):>10,} {m.get('cache_read', 0):>10,} {total:>12,} ({m['note']})")
    else:
        total = m['input_tokens'] + m['output_tokens'] + m['cache_read']
        report.append(f"{m['role']:<15} {m['task_id']:<15} {m['turns']:>6} {m['tools']:>6} {m['input_tokens']:>10,} {m['output_tokens']:>10,} {m['cache_read']:>10,} {total:>12,}")
        total_turns += m['turns']
        total_tools += m['tools']
        total_input += m['input_tokens']
        total_output += m['output_tokens']
        total_cache += m['cache_read']

report.append("-" * 80)
total_all = total_input + total_output + total_cache
report.append(f"{'TOTAL':<15} {'':<15} {total_turns:>6} {total_tools:>6} {total_input:>10,} {total_output:>10,} {total_cache:>10,} {total_all:>12,}")

report.append("")
report.append("[COMBINED: TIME + TOKENS]")
report.append("-" * 80)
report.append(f"{'Task ID':<15} {'Role':<15} {'Duration':>10} {'Turns':>6} {'Total Tokens':>13} {'Tokens/s':>10}")
report.append("-" * 80)

# Combine timing and token data
for timing in tasks_timing:
    task_id = timing['task_id']
    role = timing['role']
    duration = timing['duration_seconds']
    
    # Find matching token data
    token_data = None
    for m in token_usage:
        if m.get('task_id') == task_id and m.get('role') == role:
            token_data = m
            break
    
    if token_data and 'note' not in token_data:
        total_tokens = token_data['input_tokens'] + token_data['output_tokens'] + token_data['cache_read']
        tokens_per_sec = f"{total_tokens/duration:.0f}" if duration > 0 else "N/A"
        report.append(f"{task_id:<15} {role:<15} {duration:>9}s {token_data['turns']:>6} {total_tokens:>13,} {tokens_per_sec:>10}")
    elif token_data and 'note' in token_data:
        report.append(f"{task_id:<15} {role:<15} {duration:>9}s {token_data['turns']:>6} {'N/A':>13} {'N/A':>10} ({token_data['note']})")
    else:
        report.append(f"{task_id:<15} {role:<15} {duration:>9}s {'N/A':>6} {'N/A':>13} {'N/A':>10}")

report.append("")
report.append("[SUMMARY]")
report.append("-" * 80)
report.append(f"Total tasks: {len(tasks_timing)}")
report.append(f"Successful: {sum(1 for t in tasks_timing if t['status'] == 'COMPLETE')}")
report.append(f"Timeouts: {sum(1 for t in tasks_timing if t['status'] == 'TIMEOUT')}")
report.append(f"Review failures: {sum(1 for t in tasks_timing if t['status'] == 'REVIEW_FAILURE')}")
report.append(f"Total turns: {total_turns}")
report.append(f"Total tools: {total_tools}")
report.append(f"Total tokens: {total_all:,}")
report.append("")
report.append("[KEY FINDINGS]")
report.append("-" * 80)
report.append("1. task-1 (CODER) TIMEOUT after 600s - worker too slow for complex task")
report.append("2. task-2 (REVIEWER) found WCAG AA color contrast violation")
report.append("3. task-2 (CODER) retry successful after feedback")
report.append("4. task-3 (REVIEWER) APPROVED after 62s")
report.append("5. Run TIMEOUT after 1200s - not all tasks completed")
report.append("")
report.append("=" * 80)

# Print report
print("\n".join(report))

# Save to file
output_path = "deliverables/saas_wizard_performance_report.txt"
with open(output_path, "w", encoding="utf-8") as f:
    f.write("\n".join(report))

print(f"\nReport saved to: {output_path}")
