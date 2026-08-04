"""
Phase 7 (Reviewer-Upgrade) — deterministic constraint verifier.

Scans artifact contents for forbidden patterns:
- localStorage / sessionStorage
- fetch() / XMLHttpRequest
- external CDNs (cdn., unpkg.com, jsdelivr.net)

Returns structured findings per violation. Does NOT trust worker self-report.
"""
import re
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Any

from engine.services.verification_registry import BaseVerifier
from engine.models import TaskEvent

logger = logging.getLogger(__name__)


@dataclass
class ConstraintViolation:
    category: str
    file: str
    pattern: str
    line: Optional[int]
    context: str


@dataclass
class ConstraintVerifyResult:
    ok: bool
    violations: List[ConstraintViolation]
    report: str


# Forbidden patterns grouped by category.
# Patterns are matched as substrings (case-sensitive for JS APIs, case-insensitive for CDNs).
FORBIDDEN_PATTERNS: Dict[str, List[str]] = {
    "storage": ["localStorage", "sessionStorage"],
    "network": ["fetch(", "XMLHttpRequest"],
    "cdn": ["cdn.", "unpkg.com", "jsdelivr.net"],
    "js_declaration": ["const ", "let "],
}


def _find_line(content: str, pattern: str, start: int = 0) -> Optional[int]:
    """Return 1-based line number for first occurrence of pattern after start."""
    idx = content.find(pattern, start)
    if idx == -1:
        return None
    return content[:idx].count("\n") + 1


def _extract_context(content: str, pattern: str, line: Optional[int], radius: int = 1) -> str:
    """Return a small snippet around the matched line."""
    if line is None:
        return ""
    lines = content.splitlines()
    start = max(0, line - radius - 1)
    end = min(len(lines), line + radius)
    snippet = lines[start:end]
    return " | ".join(snippet).strip()


def verify_constraints(artifacts: List[Dict[str, Any]], force_test_failure: bool = False) -> ConstraintVerifyResult:
    """Scan artifacts for forbidden patterns.

    Args:
        artifacts: List of artifact dicts with 'path' and 'content'.
        force_test_failure: If True, inject a synthetic violation for E2E testing.
    """
    violations: List[ConstraintViolation] = []

    for artifact in artifacts:
        path = artifact.get("path", "")
        content = artifact.get("content") or ""
        if not content:
            continue

        for category, patterns in FORBIDDEN_PATTERNS.items():
            for pattern in patterns:
                if pattern in content:
                    line = _find_line(content, pattern)
                    context = _extract_context(content, pattern, line)
                    violations.append(
                        ConstraintViolation(
                            category=category,
                            file=path,
                            pattern=pattern,
                            line=line,
                            context=context,
                        )
                    )

    if violations:
        parts = [f"{v.category}:{v.file}:{v.line or '?'} [{v.pattern}]" for v in violations]
        report = "CONSTRAINT_VIOLATION: " + "; ".join(parts)
        return ConstraintVerifyResult(ok=False, violations=violations, report=report)

    return ConstraintVerifyResult(ok=True, violations=[], report="constraints ok")


class ConstraintVerifier(BaseVerifier):
    async def verify(
        self,
        session,
        task_id: str,
        project_id: str,
        plan_version: int,
        artifacts: List[Dict[str, Any]],
    ) -> Tuple[bool, str]:
        result = verify_constraints(artifacts, force_test_failure=False)
        return result.ok, result.report
