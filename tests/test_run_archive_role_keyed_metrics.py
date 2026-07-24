"""
Regression tests for role-keyed worker log metrics (P0.1).

Run via: ./tools/safe_test.sh tests/test_run_archive_role_keyed_metrics.py
"""
import json
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.services.run_archive import RunArchiver


def _write_worker_log(path: Path, events):
    with path.open("w", encoding="utf-8", errors="replace") as f:
        for obj in events:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

def _tool_call_event(tool_name: str) -> Dict[str, Any]:
    return {
        "type": "message_end",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "toolCall",
                    "name": tool_name,
                    "arguments": {},
                }
            ],
            "usage": {"input": 0, "output": 0, "cacheRead": 0, "totalTokens": 0},
        },
    }

def _usage_event(total: int) -> Dict[str, Any]:
    return {
        "type": "message_update",
        "message": {
            "role": "assistant",
            "content": [],
            "usage": {"input": 0, "output": 0, "cacheRead": 0, "totalTokens": total},
        },
    }


def test_role_for_task_coding_crew():
    archiver = RunArchiver()
    assert archiver._role_for_task("pimesh/coding-crew", "task-1") == "CODER"


def test_role_for_task_reviewing_crew():
    archiver = RunArchiver()
    assert archiver._role_for_task("pimesh/reviewing-crew", "task-1") == "REVIEWER"


def test_role_for_task_planning_crew_resolves_from_task_json(tmp_path):
    crew_dir = tmp_path / "pimesh" / "planning-crew" / ".pi" / "messenger" / "crew"
    tasks_dir = crew_dir / "tasks"
    tasks_dir.mkdir(parents=True)
    (tasks_dir / "task-1.json").write_text(
        json.dumps({
            "id": "task-1",
            "firma_assignment": {"role": "RESEARCHER"},
        }),
        encoding="utf-8",
    )

    archiver = RunArchiver()
    import engine.services.run_archive as ra
    original_base = ra.BASE_DIR
    ra.BASE_DIR = str(tmp_path)
    try:
        assert archiver._role_for_task("pimesh/planning-crew", "task-1") == "RESEARCHER"
    finally:
        ra.BASE_DIR = original_base


def test_role_for_task_planning_crew_unknown_when_missing_json():
    archiver = RunArchiver()
    assert archiver._role_for_task("pimesh/planning-crew", "missing-task") == "PLANNING_CREW_UNKNOWN"


def test_collect_tool_usage_by_task_splits_same_task_id_across_crews(tmp_path):
    run_id = "run-abc"
    base = tmp_path / "tool-base"
    base.mkdir(parents=True, exist_ok=True)

    coding_dir = base / "pimesh" / "coding-crew" / ".pi" / "work" / run_id / "task-1"
    coding_dir.mkdir(parents=True)
    _write_worker_log(coding_dir / "worker.log", [
        {"type": "turn_start", "timestamp": "2026-07-24T08:00:00Z"},
        _tool_call_event("read"),
        _tool_call_event("write"),
        _tool_call_event("edit"),
    ])

    reviewing_dir = base / "pimesh" / "reviewing-crew" / ".pi" / "work" / run_id / "task-1"
    reviewing_dir.mkdir(parents=True)
    _write_worker_log(reviewing_dir / "worker.log", [
        {"type": "turn_start", "timestamp": "2026-07-24T08:00:00Z"},
        _tool_call_event("read"),
        _tool_call_event("write"),
    ])

    archiver = RunArchiver(archive_runs_dir=tmp_path / "archive", artifact_dir=tmp_path / "artifacts")
    import engine.services.run_archive as ra
    original_base = ra.BASE_DIR
    ra.BASE_DIR = str(base)
    try:
        result = archiver._collect_tool_usage_by_task(run_id)
    finally:
        ra.BASE_DIR = original_base

    assert "CODER:task-1" in result
    assert "REVIEWER:task-1" in result
    assert result["CODER:task-1"]["read"] == 1
    assert result["CODER:task-1"]["write"] == 1
    assert result["CODER:task-1"]["edit"] == 1
    assert result["REVIEWER:task-1"]["read"] == 1
    assert result["REVIEWER:task-1"]["write"] == 1


def test_collect_turn_usage_by_task_does_not_sum_roles(tmp_path):
    run_id = "run-abc"
    base = tmp_path / "turn-base"
    base.mkdir(parents=True, exist_ok=True)

    planning_dir = base / "pimesh" / "planning-crew" / ".pi" / "work" / run_id / "task-1"
    planning_dir.mkdir(parents=True)
    tasks_dir = base / "pimesh" / "planning-crew" / ".pi" / "messenger" / "crew" / "tasks"
    tasks_dir.mkdir(parents=True)
    (tasks_dir / "task-1.json").write_text(
        json.dumps({"id": "task-1", "firma_assignment": {"role": "RESEARCHER"}}),
        encoding="utf-8",
    )
    _write_worker_log(planning_dir / "worker.log", [
        {"type": "turn_start", "timestamp": "2026-07-24T08:00:00Z"},
        {"type": "turn_start", "timestamp": "2026-07-24T08:00:01Z"},
        _tool_call_event("read"),
        _usage_event(35),
    ])

    coding_dir = base / "pimesh" / "coding-crew" / ".pi" / "work" / run_id / "task-1"
    coding_dir.mkdir(parents=True)
    _write_worker_log(coding_dir / "worker.log", [
        {"type": "turn_start", "timestamp": "2026-07-24T08:01:00Z"},
        {"type": "turn_start", "timestamp": "2026-07-24T08:01:01Z"},
        {"type": "turn_start", "timestamp": "2026-07-24T08:01:02Z"},
        _tool_call_event("write"),
        _usage_event(350),
    ])

    archiver = RunArchiver(archive_runs_dir=tmp_path / "archive", artifact_dir=tmp_path / "artifacts")
    import engine.services.run_archive as ra
    original_base = ra.BASE_DIR
    ra.BASE_DIR = str(base)
    try:
        result = archiver._collect_turn_usage_by_task(run_id)
    finally:
        ra.BASE_DIR = original_base

    assert "RESEARCHER:task-1" in result
    assert "CODER:task-1" in result
    assert result["RESEARCHER:task-1"]["turn_count"] == 2
    assert result["CODER:task-1"]["turn_count"] == 3
    assert result["RESEARCHER:task-1"]["tool_calls"]["read"] == 1
    assert result["CODER:task-1"]["tool_calls"]["write"] == 1
    assert result["RESEARCHER:task-1"]["token_usage"]["total_tokens"] == 35
    assert result["CODER:task-1"]["token_usage"]["total_tokens"] == 350


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        test_role_for_task_coding_crew()
        test_role_for_task_reviewing_crew()
        test_role_for_task_planning_crew_resolves_from_task_json(tmp)
        test_role_for_task_planning_crew_unknown_when_missing_json()
        test_collect_tool_usage_by_task_splits_same_task_id_across_crews(tmp)
        test_collect_turn_usage_by_task_does_not_sum_roles(tmp)
    print("OK")
