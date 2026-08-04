#!/usr/bin/env python3
"""
Analyze run performance: per-agent timing and token consumption.

Parses:
- run.log for task start/end timestamps
- worker.log files for token usage metrics

Outputs a structured performance report.
"""
import re
import glob
import json
import os
from datetime import datetime
from pathlib import Path
from collections import defaultdict

def parse_run_log(run_log_path):
    """Parse run.log to extract task start/end timestamps."""
    tasks = {}
    
    with open(run_log_path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            
            # Match task assignment events
            match = re.search(r'Task (task-\d+|[a-f0-9-]+) assigned\.', line)
            if match:
                task_id = match.group(1)
                timestamp_str = line.split(' ')[0] + ' ' + line.split(' ')[1]
                try:
                    timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    if task_id not in tasks:
                        tasks[task_id] = {'start': timestamp, 'end': None, 'events': []}
                    tasks[task_id]['start'] = timestamp
                except:
                    pass
            
            # Match task completion events
            match = re.search(r'Task (task-\d+|[a-f0-9-]+) (COMPLETE|FAILED)', line)
            if match:
                task_id = match.group(1)
                status = match.group(2)
                timestamp_str = line.split(' ')[0] + ' ' + line.split(' ')[1]
                try:
                    timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    if task_id in tasks:
                        tasks[task_id]['end'] = timestamp
                        tasks[task_id]['status'] = status
                except:
                    pass
    
    return tasks


def parse_worker_logs(run_id):
    """Parse all worker logs for a run to extract token metrics."""
    pattern = f'pimesh/**/.pi/work/{run_id}/*/worker.log'
    logs = glob.glob(pattern, recursive=True)
    
    results = []
    for log_path in logs:
        parts = log_path.replace('\\', '/').split('/')
        role = parts[1] if len(parts) > 1 else '?'
        task_id = parts[-2] if len(parts) > 1 else '?'
        
        # Parse with existing parser
        from engine.services.worker_log_parser import parse_worker_log
        metrics = parse_worker_log(Path(log_path))
        
        usage = metrics.token_usage or {}
        results.append({
            'role': role,
            'task_id': task_id,
            'turn_count': metrics.turn_count,
            'tool_calls': sum(metrics.tool_calls.values()) if isinstance(metrics.tool_calls, dict) else 0,
            'input_tokens': usage.get('input_tokens', 0),
            'output_tokens': usage.get('output_tokens', 0),
            'cache_read': usage.get('cache_read', 0),
            'cache_write': usage.get('cache_write', 0),
            'total_tokens': usage.get('input_tokens', 0) + usage.get('output_tokens', 0) + usage.get('cache_read', 0),
            'warnings': metrics.warnings,
        })
    
    return results


def main():
    run_id = '3e116b25-8146-4a45-bde8-c0e22517f21e'
    # Use absolute path for Windows compatibility
    run_log = r'C:\tmp\firma_saas_wizard_run.log'
    if not os.path.exists(run_log):
        print(f'ERROR: Run log not found at {run_log}')
        return
    
    print('=' * 80)
    print('RUN PERFORMANCE ANALYSIS')
    print('=' * 80)
    print()
    
    # Parse run log
    print('[TASK TIMING] (from run.log)')
    print('-' * 80)
    tasks = parse_run_log(run_log)
    
    for task_id, data in tasks.items():
        if data.get('start') and data.get('end'):
            duration = (data['end'] - data['start']).total_seconds()
            status = data.get('status', 'UNKNOWN')
            print(f'{task_id:15} | Start: {data["start"].strftime("%H:%M:%S")} | End: {data["end"].strftime("%H:%M:%S")} | Duration: {duration:6.1f}s | Status: {status}')
        elif data.get('start'):
            print(f'{task_id:15} | Start: {data["start"].strftime("%H:%M:%S")} | End:   N/A | Duration:    N/A | Status: RUNNING')
        else:
            print(f'{task_id:15} | Start:   N/A | End:   N/A | Duration:    N/A | Status: UNKNOWN')
    
    print()
    print('[TOKEN USAGE] (from worker.log)')
    print('-' * 80)
    
    # Parse worker logs
    metrics = parse_worker_logs(run_id)
    
    if not metrics:
        print('No worker logs found!')
        return
    
    # Header
    print(f'{"Role/Task":<30} {"Turns":>6} {"Tools":>6} {"Input":>10} {"Output":>10} {"CacheR":>10} {"Total":>12}')
    print('-' * 90)
    
    total_turns = 0
    total_tools = 0
    total_input = 0
    total_output = 0
    total_cache = 0
    
    for m in sorted(metrics, key=lambda x: x['role'] + '/' + x['task_id']):
        label = f"{m['role']}/{m['task_id']}"
        print(f'{label:<30} {m["turn_count"]:>6} {m["tool_calls"]:>6} {m["input_tokens"]:>10,} {m["output_tokens"]:>10,} {m["cache_read"]:>10,} {m["total_tokens"]:>12,}')
        
        total_turns += m['turn_count']
        total_tools += m['tool_calls']
        total_input += m['input_tokens']
        total_output += m['output_tokens']
        total_cache += m['cache_read']
    
    print('-' * 90)
    total_all = total_input + total_output + total_cache
    print(f'{"TOTAL":<30} {total_turns:>6} {total_tools:>6} {total_input:>10,} {total_output:>10,} {total_cache:>10,} {total_all:>12,}')
    
    print()
    print('[COMBINED] TIME + TOKENS')
    print('-' * 80)
    
    # Combine timing and token data
    print(f'{"Task":<15} {"Role":<15} {"Duration":>10} {"Turns":>6} {"Total Tokens":>13} {"Tokens/s":>10}')
    print('-' * 80)
    
    for m in sorted(metrics, key=lambda x: x['role'] + '/' + x['task_id']):
        task_id = m['task_id']
        role = m['role']
        
        # Find corresponding timing data
        duration = None
        if task_id in tasks:
            task_data = tasks[task_id]
            if task_data.get('start') and task_data.get('end'):
                duration = (task_data['end'] - task_data['start']).total_seconds()
        
        duration_str = f'{duration:.1f}s' if duration is not None else 'N/A'
        tokens_per_sec = f'{m["total_tokens"]/duration:.0f}' if duration and duration > 0 else 'N/A'
        
        print(f'{task_id:<15} {role:<15} {duration_str:>10} {m["turn_count"]:>6} {m["total_tokens"]:>13,} {tokens_per_sec:>10}')


if __name__ == '__main__':
    main()
