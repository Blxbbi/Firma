"""
Tests for kernel-side plan validation in GuardianPipeline.
"""
from __future__ import annotations

import pytest

from engine.services.guardian import GuardianPipeline


def _validate(plan_data):
    return GuardianPipeline.validate_plan_draft(plan_data)


def test_valid_plan_passes():
    plan = {
        "plan_name": "ok",
        "tasks": [
            {"id": "task-1", "role": "CODER", "expected_artifacts": [{"path": "a.py", "type": "CREATE"}]},
            {"id": "task-2", "role": "CODER", "expected_artifacts": [{"path": "b.py", "type": "CREATE"}]},
        ],
    }
    ok, issues = _validate(plan)
    assert ok is True
    assert issues == []


def test_rejects_empty_tasks():
    ok, issues = _validate({"plan_name": "x", "tasks": []})
    assert ok is False
    assert "no tasks" in issues[0]


def test_rejects_more_than_ten_tasks():
    tasks = [{"id": f"t{i}", "role": "CODER", "expected_artifacts": [{"path": "f.py", "type": "CREATE"}]} for i in range(11)]
    ok, issues = _validate({"plan_name": "x", "tasks": tasks})
    assert ok is False
    assert any("max 10" in i for i in issues)


def test_rejects_coder_task_without_expected_artifacts():
    plan = {
        "plan_name": "x",
        "tasks": [
            {"id": "task-1", "role": "CODER", "expected_artifacts": []},
        ],
    }
    ok, issues = _validate(plan)
    assert ok is False
    assert any("no expected_artifacts" in i for i in issues)


def test_rejects_task_with_too_many_expected_artifacts():
    plan = {
        "plan_name": "x",
        "tasks": [
            {"id": "task-1", "role": "CODER", "expected_artifacts": [
                {"path": "a.py", "type": "CREATE"},
                {"path": "b.py", "type": "CREATE"},
                {"path": "c.py", "type": "CREATE"},
                {"path": "d.py", "type": "CREATE"},
            ]},
        ],
    }
    ok, issues = _validate(plan)
    assert ok is False
    assert any("max 3" in i for i in issues)


def test_allows_non_coder_without_artifacts():
    plan = {
        "plan_name": "x",
        "tasks": [
            {"id": "task-1", "role": "REVIEWER", "expected_artifacts": []},
        ],
    }
    ok, issues = _validate(plan)
    assert ok is True
    assert issues == []
