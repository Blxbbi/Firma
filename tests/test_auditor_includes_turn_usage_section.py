"""
Integration-style test for auditor turn-usage rendering.

Keeps the test deterministic by feeding a pre-built report dict into
``RunAuditor._render_md`` only. This avoids DB/controller coupling while still
verifying that the new section is rendered with real fixture data.
"""
from __future__ import annotations

import pytest

from engine.services.auditor import RunAuditor


def test_turn_usage_section_in_audit_md() -> None:
    auditor = RunAuditor()
    report = {
        "run_id": "test-turn-usage-run",
        "terminal_state": "COMPLETED",
        "overview": {
            "run_id": "test-turn-usage-run",
            "app": "test",
            "transport": "n/a",
            "terminal_state": "COMPLETED",
            "started_at": "2026-07-23T11:27:39.196178",
            "completed_at": "2026-07-23T11:32:47.735766",
            "duration_seconds": 308.54,
            "persona_id": None,
            "session_mode": None,
        },
        "task_table": [
            {
                "task_id": "task-1",
                "role": "CODER",
                "terminal_state": "COMPLETE",
                "attempts": 1,
                "last_event": "COMPLETE",
                "verifier": "n/a",
            }
        ],
        "scope_summary": [],
        "research": {"present": False, "note": "no research phase"},
        "failures": [],
        "artifacts": {
            "artifact_refs_count": 0,
            "artifact_refs": [],
            "deliverables_dir": None,
            "note": "deliverables are not copied into the archive in V1",
        },
        "repro_env": {},
        "tool_usage": {"by_task": {"task-1": {"read": 1, "write": 1}}, "by_role": {"CODER": {"read": 1, "write": 1}}},
        "tool_policy_checks": [],
        "turn_usage": {
            "by_task": {
                "task-1": {
                    "task_id": "task-1",
                    "turn_count": 2,
                    "tool_calls": {"read": 1, "write": 1},
                    "token_usage": {
                        "total_tokens": 25,
                        "input_tokens": 22,
                        "output_tokens": 3,
                        "cache_read": 0,
                    },
                    "warnings": [],
                }
            },
            "by_role": {
                "CODER": {
                    "tasks": 1,
                    "turns": 2,
                    "tool_calls": 2,
                    "warnings": [],
                }
            },
        },
        "sections_present": [
            "overview",
            "task_table",
            "scope_summary",
            "research",
            "failures",
            "artifacts",
            "repro_env",
            "tool_usage",
            "tool_policy_checks",
            "turn_usage",
        ],
        "warnings": [],
    }

    md = auditor._render_md(report)
    assert "## 10. Turn Usage by Role" in md
    assert "- turns: 2" in md
    assert "- tool_calls: 2" in md
    assert "### CODER" in md
