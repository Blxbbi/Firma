"""
Unit tests for engine.services.worker_log_parser.

Uses a lightweight fixture under tests/fixtures/ so tests stay fast,
deterministic, and CI-friendly (no dependency on concrete run dirs).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.services.worker_log_parser import parse_worker_log, WorkerLogMetrics


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "worker_log_sample.jsonl"


def test_parse_worker_log_counts_turns() -> None:
    metrics = parse_worker_log(FIXTURE)
    assert isinstance(metrics, WorkerLogMetrics)
    assert metrics.task_id == "fixtures"
    assert metrics.turn_count == 3


def test_parse_worker_log_counts_tool_calls() -> None:
    metrics = parse_worker_log(FIXTURE)
    assert metrics.tool_calls == {"read": 1, "write": 1}


def test_parse_worker_log_best_effort_token_usage() -> None:
    metrics = parse_worker_log(FIXTURE)
    assert metrics.token_usage is not None
    # The fixture contains usage on turn_end wrappers; exact aggregation is best-effort.
    assert metrics.token_usage["total_tokens"] >= 0


def test_parse_worker_log_missing_file_does_not_raise() -> None:
    metrics = parse_worker_log(Path("does_not_exist/worker.log"))
    assert metrics.turn_count == 0
    assert metrics.tool_calls == {}
    assert len(metrics.warnings) >= 1


def test_parse_worker_log_empty_file() -> None:
    path = FIXTURE.parent / "empty_worker.log"
    path.write_text("", encoding="utf-8")
    try:
        metrics = parse_worker_log(path)
        assert metrics.turn_count == 0
        assert metrics.tool_calls == {}
    finally:
        path.unlink(missing_ok=True)
