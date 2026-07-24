"""
Worker-Log-Parser (zentral, single source of truth).

Parses ``worker.log`` files produced by pi-messenger crew workers and extracts:
- turn count (``turn_start`` events)
- tool calls by name
- token usage (best-effort, only if present and consistent)

Dieses Modul wird von ``run_archive.py`` verwendet.
Der Auditor darf es nicht duplizieren; er rendert nur aus dem Archiv/Manifest.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, List


@dataclass
class WorkerLogMetrics:
    task_id: str
    turn_count: int = 0
    tool_calls: Dict[str, int] = field(default_factory=dict)
    token_usage: Optional[Dict[str, int]] = None
    warnings: list[str] = field(default_factory=list)
    phase_timing: Optional[Dict[str, Any]] = None
    error_events: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "turn_count": self.turn_count,
            "tool_calls": dict(self.tool_calls),
            "token_usage": self.token_usage,
            "warnings": list(self.warnings),
            "phase_timing": self.phase_timing,
            "error_events": list(self.error_events),
        }


def _parse_token_usage(message: Dict[str, Any]) -> Optional[Dict[str, int]]:
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None
    total = usage.get("totalTokens") or usage.get("total_tokens")
    inp = usage.get("input") or usage.get("input_tokens")
    out = usage.get("output") or usage.get("output_tokens")
    cache_read = usage.get("cacheRead") or usage.get("cache_read")
    if total is None and inp is None and out is None and cache_read is None:
        return None
    return {
        "total_tokens": int(total or 0),
        "input_tokens": int(inp or 0),
        "output_tokens": int(out or 0),
        "cache_read": int(cache_read or 0),
    }


def _safe_iso(ts_str: Optional[str]) -> Optional[str]:
    if not isinstance(ts_str, str) or not ts_str:
        return None
    try:
        return ts_str
    except Exception:
        return None


def _parse_phase_timing(lines: List[str]) -> Optional[Dict[str, Any]]:
    """Extract rough phase timing from worker.log timestamps.

    Best-effort: uses first/last timestamps and turn_start events.
    Returns None if no usable timestamps are found.
    """
    first_ts = None
    last_ts = None
    turn_timestamps: List[str] = []

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        ts = obj.get("timestamp")
        if isinstance(ts, str) and ts:
            if first_ts is None:
                first_ts = ts
            last_ts = ts
        if obj.get("type") == "turn_start" and isinstance(ts, str) and ts:
            turn_timestamps.append(ts)

    if first_ts is None or last_ts is None:
        return None

    try:
        t0 = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
        duration_s = round((t1 - t0).total_seconds(), 3)
    except Exception:
        return None

    first_turn_gap_s = None
    if len(turn_timestamps) >= 2:
        try:
            t_first = datetime.fromisoformat(turn_timestamps[0].replace("Z", "+00:00"))
            t_second = datetime.fromisoformat(turn_timestamps[1].replace("Z", "+00:00"))
            first_turn_gap_s = round((t_second - t_first).total_seconds(), 3)
        except Exception:
            pass

    return {
        "first_event_at": first_ts,
        "last_event_at": last_ts,
        "duration_s": duration_s,
        "turn_count_ts": len(turn_timestamps),
        "first_turn_gap_s": first_turn_gap_s,
    }


def _is_error_event(obj: Dict[str, Any]) -> bool:
    event_type = obj.get("type", "")
    return event_type in (
        "error",
        "agent_error",
        "task_failed",
        "worker_timeout",
        "plan_rejected",
        "review_failure",
        "verify_failure",
    )


def parse_worker_log(path: Path) -> WorkerLogMetrics:
    metrics = WorkerLogMetrics(task_id=path.parent.name)
    token_aggregate: Optional[Dict[str, int]] = None
    token_samples: int = 0
    first_token_source: bool = False
    lines: List[str] = []

    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                lines.append(line)
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if not isinstance(obj, dict):
                    continue

                event_type = obj.get("type", "")

                if event_type == "turn_start":
                    metrics.turn_count += 1
                    continue

                if event_type in ("turn_end", "message_end"):
                    inner_msg = obj.get("message")
                    if isinstance(inner_msg, dict):
                        content = inner_msg.get("content")
                        if isinstance(content, list):
                            for item in content:
                                if not isinstance(item, dict):
                                    continue
                                if item.get("type") != "toolCall":
                                    continue
                                tool_name = (item.get("name") or "").strip().lower()
                                if not tool_name:
                                    continue
                                if "bash" in tool_name:
                                    normalized = "bash"
                                elif "read" in tool_name:
                                    normalized = "read"
                                elif "write" in tool_name:
                                    normalized = "write"
                                elif "edit" in tool_name:
                                    normalized = "edit"
                                else:
                                    normalized = tool_name
                                metrics.tool_calls[normalized] = metrics.tool_calls.get(normalized, 0) + 1

                msg = None
                if event_type in ("message_start", "message_end", "message_update"):
                    msg = obj.get("message") or obj.get("assistantMessageEvent", {}).get("partial")
                if isinstance(msg, dict):
                    usage = _parse_token_usage(msg)
                    if usage is not None:
                        token_samples += 1
                        first_token_source = True
                        if token_aggregate is None:
                            token_aggregate = dict(usage)
                        else:
                            for k, v in usage.items():
                                token_aggregate[k] = token_aggregate.get(k, 0) + int(v or 0)

                if _is_error_event(obj):
                    metrics.error_events.append({
                        "type": event_type,
                        "timestamp": obj.get("timestamp"),
                        "message": obj.get("message") or obj.get("error") or obj.get("reason"),
                    })
    except Exception as exc:
        metrics.warnings.append(f"parse_failed:{exc}")

    if first_token_source and token_aggregate is not None:
        if token_samples > 1:
            metrics.warnings.append(
                f"token_usage_aggregated_from_{token_samples}_events"
            )
        metrics.token_usage = token_aggregate
    else:
        metrics.warnings.append("token_usage_unavailable")

    timing = _parse_phase_timing(lines)
    if timing is not None:
        # If duration is 0.0 and turn_count_ts is 0, timing is unreliable
        if timing.get("duration_s") == 0.0 and timing.get("turn_count_ts", 0) == 0:
            metrics.warnings.append("phase_timing_unavailable_no_timestamps")
            metrics.phase_timing = None
        else:
            metrics.phase_timing = timing

    return metrics
