#!/usr/bin/env python3
"""Measure token savings from prompt optimization."""
import sys
import os
import tempfile
import glob
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.transport.pi_mesh_transport import PiMeshTransport
from engine.services.worker_log_parser import parse_worker_log

CREWS = {
    "PLANNER": "pimesh/planning-crew",
    "CODER": "pimesh/coding-crew",
    "REVIEWER": "pimesh/reviewing-crew",
    "RESEARCHER": "pimesh/planning-crew",
}


def measure_spec_sizes():
    """Measure optimized spec sizes for each role."""
    root = tempfile.mkdtemp()
    t = PiMeshTransport(crew_cwds=CREWS, project_root=root)

    payload = {
        "run_id": "test-run",
        "task_id": "task-3",
        "state_revision": 7,
        "prompt": "Implementiere die folgende Task als CODER.",
        "task_definition": {
            "task_id": "task-3",
            "description": "Fuege app.js hinzu: Vanilla-JS-Interaktivitaet.",
            "acceptance_criteria": [
                "Mobile-Navigation oeffnet und schliesst zuverlaessig",
                "Smooth-Scrolling funktioniert fuer alle Anker-Links",
                "Keine JavaScript-Fehler erscheinen in der Browser-Konsole",
                "Aktiver Navigationspunkt aktualisiert sich beim Scrollen",
                "Seite ist auch bei deaktiviertem JavaScript grundlegend bedienbar",
            ],
            "expected_artifacts": [{"path": "app.js", "type": "CREATE"}],
        },
    }

    review_artifacts = {
        "app.js": "(function() { 'use strict'; /* ... */ })();",
    }

    print("=== OPTIMIZED SPEC SIZES ===")
    print(f"{'Role':<15} {'Spec Size':>12} {'Lines':>8}")
    print("-" * 40)

    for role in ["PLANNER", "CODER", "REVIEWER", "RESEARCHER"]:
        payload["role"] = role
        if role == "REVIEWER":
            spec = t._build_spec_markdown(payload, root, review_artifacts)
        else:
            spec = t._build_spec_markdown(payload, root)
        lines = spec.count("\n")
        print(f"{role:<15} {len(spec):>12,} {lines:>8}")


def measure_run_tokens(run_id: str):
    """Measure actual token usage from a run's worker logs."""
    pattern = f"pimesh/**/.pi/work/{run_id}/*/worker.log"
    logs = glob.glob(pattern, recursive=True)

    if not logs:
        print(f"\nNo worker logs found for run {run_id}")
        return

    print(f"\n=== TOKEN USAGE FOR RUN {run_id} ===")
    print(f"{'Role/Task':<30} {'Turns':>6} {'Tools':>6} {'Input':>10} {'Output':>10} {'CacheR':>10} {'Total':>12}")
    print("-" * 90)

    total_turns = 0
    total_tools = 0
    total_input = 0
    total_output = 0
    total_cache = 0

    for log_path in sorted(logs):
        parts = log_path.replace("\\", "/").split("/")
        role = parts[1] if len(parts) > 1 else "?"
        task_id = parts[-2] if len(parts) > 1 else "?"

        metrics = parse_worker_log(Path(log_path))
        usage = metrics.token_usage or {}
        inp = usage.get("input_tokens", 0)
        outp = usage.get("output_tokens", 0)
        cr = usage.get("cache_read", 0)
        total = inp + outp + cr
        tool_calls = (
            sum(metrics.tool_calls.values()) if isinstance(metrics.tool_calls, dict) else 0
        )

        label = f"{role}/{task_id}"
        print(f"{label:<30} {metrics.turn_count:>6} {tool_calls:>6} {inp:>10,} {outp:>10,} {cr:>10,} {total:>12,}")

        total_turns += metrics.turn_count
        total_tools += tool_calls
        total_input += inp
        total_output += outp
        total_cache += cr

    print("-" * 90)
    total_all = total_input + total_output + total_cache
    print(
        f"{'TOTAL':<30} {total_turns:>6} {total_tools:>6} "
        f"{total_input:>10,} {total_output:>10,} {total_cache:>10,} {total_all:>12,}"
    )


if __name__ == "__main__":
    measure_spec_sizes()
    measure_run_tokens("3c12694f-685f-404b-8496-7ec77ad30f8c")
