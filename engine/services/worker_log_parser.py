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
from pathlib import Path
from typing import Dict, Optional


@dataclass
class WorkerLogMetrics:
    task_id: str
    turn_count: int = 0
    tool_calls: Dict[str, int] = field(default_factory=dict)
    token_usage: Optional[Dict[str, int]] = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "turn_count": self.turn_count,
            "tool_calls": dict(self.tool_calls),
            "token_usage": self.token_usage,
            "warnings": list(self.warnings),
        }


def _parse_token_usage(message: Dict[str, Any]) -> Optional[Dict[str, int]]:
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None
    # Support both camelCase and snake_case keys.
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


def parse_worker_log(path: Path) -> WorkerLogMetrics:
    metrics = WorkerLogMetrics(task_id=path.parent.name)
    token_aggregate: Optional[Dict[str, int]] = None
    token_samples: int = 0
    first_token_source: bool = False

    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Current format: top-level event objects.
                if not isinstance(obj, dict):
                    continue

                event_type = obj.get("type", "")

                if event_type == "turn_start":
                    metrics.turn_count += 1
                    continue

                # Extract tool calls from turn_end wrappers.
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

                # Extract/best-effort token usage.
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
                            # Aggregate by summing; identical structure assumed.
                            for k, v in usage.items():
                                token_aggregate[k] = token_aggregate.get(k, 0) + int(v or 0)

    except Exception as exc:  # defensive: never let parsing crash archiving/auditing
        metrics.warnings.append(f"parse_failed:{exc}")

    if first_token_source and token_aggregate is not None:
        if token_samples > 1:
            metrics.warnings.append(
                f"token_usage_aggregated_from_{token_samples}_events"
            )
        metrics.token_usage = token_aggregate
    else:
        metrics.warnings.append("token_usage_unavailable")

    return metrics
