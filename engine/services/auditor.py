"""
Phase 4 (Idee C) — RunAuditor: read-only, deterministic run auditing.

After a run reaches a terminal state and is archived, the Auditor aggregates the
archive manifest + DB into a human-readable ``audit.md`` and a machine-readable
``audit.json`` inside ``archive/runs/<run_id>/``.

Design rules (V1):
  - STRICTLY READ-ONLY. Reads the archive + DB, writes only the two report files.
  - LLM-FREE. No "executive summary", no hallucination. Hard numbers + links.
  - GRACEFUL. Missing optional fields/sections never crash the report.
  - GUARD INFERENCE is a deterministic heuristic over the TaskTransitionLog; unknown
    cases are explicitly marked "unknown (see transition log)" — never invented.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from engine.models import Task, TaskTransitionLog


class RunAuditor:
    """Aggregates a run's archive + DB into audit.md / audit.json (read-only)."""

    async def write_report(
        self, run_id: str, run_dir: Any, controller: Any
    ) -> Dict[str, Any]:
        run_dir = Path(run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)

        warnings: List[str] = []
        manifest = await self._read_json(run_dir / "manifest.json") or {}
        db_snap = await self._read_json(run_dir / "db_snapshot.json") or {}

        # ---- Run-level status (authoritative from DB via controller)
        status: Dict[str, Any] = {}
        try:
            status = await controller.get_run_status(run_id) or {}
        except Exception as exc:  # defensive
            warnings.append(f"get_run_status failed: {exc}")

        tasks: List[Task] = []
        transitions: Dict[str, List[TaskTransitionLog]] = {}
        try:
            async with controller.db.session_scope() as session:
                res = await session.execute(select(Task).filter(Task.run_id == run_id))
                tasks = list(res.scalars().all())
                if tasks:
                    tres = await session.execute(
                        select(TaskTransitionLog).filter(
                            TaskTransitionLog.task_id.in_([t.id for t in tasks])
                        )
                    )
                    for tr in tres.scalars().all():
                        transitions.setdefault(tr.task_id, []).append(tr)
        except Exception as exc:  # defensive: report what we have
            warnings.append(f"db read failed: {exc}")

        report = self._build_report(
            run_id, manifest, db_snap, status, tasks, transitions, run_dir, warnings
        )

        audit_md = run_dir / "audit.md"
        audit_json = run_dir / "audit.json"
        audit_md.write_text(self._render_md(report), encoding="utf-8")
        self._write_json(audit_json, report)
        report["audit_md"] = str(audit_md)
        report["audit_json"] = str(audit_json)
        return report

    # ----------------------------------------------------------- internal build
    def _build_report(
        self, run_id, manifest, db_snap, status, tasks, transitions, run_dir, warnings
    ) -> Dict[str, Any]:
        terminal_state = (
            status.get("status")
            or manifest.get("terminal_state")
            or db_snap.get("terminal_state")
            or "UNKNOWN"
        )
        started_at = (
            status.get("started_at")
            or manifest.get("started_at")
            or db_snap.get("started_at")
        )
        completed_at = status.get("completed_at")
        duration = self._duration_seconds(started_at, completed_at)

        overview = {
            "run_id": run_id,
            "app": manifest.get("app") or status.get("app"),
            "transport": manifest.get("transport"),
            "terminal_state": terminal_state,
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_seconds": duration,
            "persona_id": (manifest.get("config_snapshot") or {}).get("FIRMA_PERSONA_ID"),
            "session_mode": (manifest.get("config_snapshot") or {}).get("SESSION_MODE"),
        }

        task_table = []
        failures: List[Dict[str, Any]] = []
        for t in tasks:
            last_ev = self._last_event(transitions.get(t.id))
            guard = self._infer_guard(t, transitions)
            verifier = t.verification_type or "n/a"
            task_table.append({
                "task_id": t.id,
                "role": t.assigned_role,
                "terminal_state": t.state,
                "attempts": t.attempt_count,
                "retries": t.retry_count,
                "last_event": last_ev or t.execution_phase,
                "verifier": verifier,
            })
            if t.state in ("FAILED", "FAILED_ITERATION_LIMIT"):
                failures.append({
                    "task_id": t.id,
                    "role": t.assigned_role,
                    "state": t.state,
                    "execution_phase": t.execution_phase,
                    "last_event": last_ev,
                    "guard": guard,
                    "review_feedback": t.last_review_feedback,
                })

        scope_summary = self._scope_summary(manifest, run_dir)
        research = self._research_summary(run_dir)
        artifacts = self._artifacts_section(manifest, run_dir)
        repro_env = self._repro_env(manifest)
        tool_usage = self._tool_usage_section(manifest, tasks)
        policy_checks = self._tool_policy_checks(manifest, tasks)
        turn_usage = self._turn_usage_section(manifest, tasks)

        # run-level failure reason (governance/guard messages live here)
        run_failure = (
            status.get("failure_reason")
            or db_snap.get("failure_reason")
            or manifest.get("failure_reason")
        )
        if run_failure and not failures:
            failures.append({"task_id": None, "guard": "run_level", "reason": run_failure})

        report = {
            "run_id": run_id,
            "terminal_state": terminal_state,
            "overview": overview,
            "task_table": task_table,
            "scope_summary": scope_summary,
            "research": research,
            "failures": failures,
            "artifacts": artifacts,
            "repro_env": repro_env,
            "tool_usage": tool_usage,
            "tool_policy_checks": policy_checks,
            "turn_usage": turn_usage,
            "sections_present": [
                "overview", "task_table", "scope_summary", "research",
                "failures", "artifacts", "repro_env",
                "tool_usage", "tool_policy_checks", "turn_usage",
            ],
            "warnings": warnings,
        }
        return report

    # --------------------------------------------------------------- sections
    def _tool_usage_section(self, manifest, tasks) -> Dict[str, Any]:
        usage_by_task = manifest.get("tool_usage_by_task") or {}
        by_role: Dict[str, Dict[str, int]] = {}
        for t in tasks:
            task_usage = usage_by_task.get(t.id, {})
            role = t.assigned_role or "UNKNOWN"
            role_usage = by_role.setdefault(role, {})
            for tool_name, count in task_usage.items():
                role_usage[tool_name] = role_usage.get(tool_name, 0) + count
        return {
            "by_task": usage_by_task,
            "by_role": by_role,
        }

    def _tool_policy_checks(self, manifest, tasks) -> List[Dict[str, Any]]:
        checks: List[Dict[str, Any]] = []
        usage_by_task = manifest.get("tool_usage_by_task") or {}
        for t in tasks:
            task_usage = usage_by_task.get(t.id, {})
            role = t.assigned_role or "UNKNOWN"
            violations: List[str] = []
            if role == "REVIEWER":
                for forbidden in ("edit", "bash", "glob", "grep"):
                    if task_usage.get(forbidden, 0) > 0:
                        violations.append(f"forbidden_tool:{forbidden}={task_usage[forbidden]}")
            check = {
                "task_id": t.id,
                "role": role,
                "tool_usage": task_usage,
                "policy_violations": violations,
                "ok": len(violations) == 0,
            }
            checks.append(check)
        return checks

    def _turn_usage_section(self, manifest, tasks) -> Dict[str, Any]:
        turn_by_task = manifest.get("turn_usage_by_task") or {}
        by_role: Dict[str, Dict[str, Any]] = {}
        for t in tasks:
            task_turn = turn_by_task.get(t.id, {})
            role = t.assigned_role or "UNKNOWN"
            role_agg = by_role.setdefault(role, {
                "tasks": 0,
                "turns": 0,
                "tool_calls": 0,
                "warnings": [],
            })
            role_agg["tasks"] += 1
            role_agg["turns"] += task_turn.get("turn_count", 0) or 0
            role_agg["tool_calls"] += sum(task_turn.get("tool_calls", {}).values())
            role_agg["warnings"].extend(task_turn.get("warnings") or [])
        return {
            "by_task": turn_by_task,
            "by_role": by_role,
        }

    def _scope_summary(self, manifest, run_dir) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        scope = manifest.get("scope_summary")
        if not scope:
            return out
        # best-effort re-check of actual drift (workspace + baseline may be gone)
        from engine.services.verifiers.scope_verifier import verify_scope
        ws = manifest.get("workspace_root")
        base = manifest.get("baseline_manifest")
        base_path = os.path.join(str(run_dir), base) if base else None
        for tid, sc in scope.items():
            entry = {"task_id": tid, "scope_files": sc.get("scope_files", []),
                     "protected_files": sc.get("protected_files", [])}
            if ws and base_path and os.path.isdir(ws) and os.path.exists(base_path):
                try:
                    res = verify_scope(
                        ws, base_path,
                        scope_files=sc.get("scope_files"),
                        protected_files=sc.get("protected_files"),
                    )
                    entry["recheck"] = {
                        "ok": res.ok, "code": res.code,
                        "changed": res.changed, "new": res.new, "removed": res.removed,
                    }
                except Exception:
                    entry["recheck"] = "skipped (verify error)"
            out.append(entry)
        return out

    def _research_summary(self, run_dir) -> Dict[str, Any]:
        brief = run_dir / "research_brief.md"
        if brief.exists():
            try:
                text = brief.read_text(encoding="utf-8", errors="replace")
            except Exception:
                text = ""
            head = "\n".join(text.splitlines()[:8])
            return {"present": True, "link": "research_brief.md", "excerpt": head}
        return {"present": False, "note": "no research phase"}

    def _artifacts_section(self, manifest, run_dir) -> Dict[str, Any]:
        refs = manifest.get("artifact_refs") or []
        deliverables = None
        # V1: deliverables live outside the archive; report if discoverable nearby.
        cand = run_dir.parent.parent / "deliverables" if run_dir.parent.parent else None
        return {
            "artifact_refs_count": len(refs),
            "artifact_refs": refs[:20],
            "deliverables_dir": str(cand) if cand else None,
            "note": "deliverables are not copied into the archive in V1",
        }

    def _repro_env(self, manifest) -> Dict[str, Any]:
        snap = manifest.get("config_snapshot") or {}
        env = {k: v for k, v in snap.items() if k.startswith("FIRMA") or k in ("SESSION_MODE",)}
        return env

    # ----------------------------------------------------------- heuristics
    @staticmethod
    def _last_event(transitions) -> Optional[str]:
        if not transitions:
            return None
        ts = sorted(transitions, key=lambda t: t.timestamp or datetime.min.replace(tzinfo=timezone.utc))
        return ts[-1].event if ts else None

    @staticmethod
    def _infer_guard(task: Task, transitions) -> Optional[str]:
        if task.state not in ("FAILED", "FAILED_ITERATION_LIMIT"):
            return None
        if task.execution_phase == "RESEARCHING":
            return "research_readonly_guard"
        last_ev = RunAuditor._last_event(transitions.get(task.id))
        if last_ev == "WORKER_TIMEOUT":
            return "worker_timeout_guard"
        if last_ev == "VERIFY_FAILURE":
            return f"verifier_guard ({task.verification_type or 'unknown'})"
        if last_ev == "TASK_FAILED":
            return "governance_guard"
        return "unknown (see transition log)"

    @staticmethod
    def _duration_seconds(started_at, completed_at) -> Optional[float]:
        if not started_at or not completed_at:
            return None
        try:
            s = datetime.fromisoformat(started_at)
            e = datetime.fromisoformat(completed_at)
            return round((e - s).total_seconds(), 3)
        except Exception:
            return None

    # --------------------------------------------------------------- io
    async def _read_json(self, path: Path) -> Optional[Dict[str, Any]]:
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return None

    @staticmethod
    def _write_json(path: Path, data: Any) -> None:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # --------------------------------------------------------------- render
    def _render_md(self, r: Dict[str, Any]) -> str:
        L: List[str] = []
        ov = r["overview"]
        L.append(f"# Run Audit: {r['run_id']}")
        L.append("")
        L.append("## 1. Run Overview")
        L.append(f"- run_id: `{ov['run_id']}`")
        L.append(f"- app: {ov.get('app') or 'n/a'}")
        L.append(f"- transport: {ov.get('transport') or 'n/a'}")
        L.append(f"- terminal_state: **{ov.get('terminal_state')}**")
        L.append(f"- started_at: {ov.get('started_at') or 'n/a'}")
        L.append(f"- completed_at: {ov.get('completed_at') or 'n/a'}")
        L.append(f"- duration_seconds: {ov.get('duration_seconds') if ov.get('duration_seconds') is not None else 'n/a'}")
        L.append(f"- persona_id: {ov.get('persona_id') or 'n/a'}")
        L.append(f"- session_mode: {ov.get('session_mode') or 'n/a'}")
        L.append("")

        L.append("## 2. Task Table")
        if r["task_table"]:
            L.append("| task_id | role | terminal_state | attempts | last_event | verifier |")
            L.append("|---|---|---|---|---|---|")
            for t in r["task_table"]:
                L.append(
                    f"| `{t['task_id']}` | {t['role']} | {t['terminal_state']} | "
                    f"{t['attempts']} | {t['last_event']} | {t['verifier']} |"
                )
        else:
            L.append("- (no tasks recorded)")
        L.append("")

        L.append("## 3. Scope / Drift Summary")
        if r["scope_summary"]:
            for s in r["scope_summary"]:
                L.append(f"- task `{s['task_id']}`: scope={s.get('scope_files')}, protected={s.get('protected_files')}")
                rc = s.get("recheck")
                if isinstance(rc, dict):
                    L.append(f"  - recheck: code={rc.get('code')}, changed={rc.get('changed')}, new={rc.get('new')}, removed={rc.get('removed')}")
                elif isinstance(rc, str):
                    L.append(f"  - recheck: {rc}")
        else:
            L.append("- no ingest/scope data (from-scratch run)")
        L.append("")

        L.append("## 4. Research Summary")
        rs = r["research"]
        if rs.get("present"):
            L.append(f"- research_brief: [{rs.get('link')}]({rs.get('link')})")
            if rs.get("excerpt"):
                L.append("")
                L.append("```")
                L.append(rs["excerpt"])
                L.append("```")
        else:
            L.append(f"- {rs.get('note', 'no research phase')}")
        L.append("")

        L.append("## 5. Failures & Retries")
        if r["failures"]:
            for f in r["failures"]:
                if f.get("task_id"):
                    L.append(f"- task `{f['task_id']}` ({f.get('role')}): state={f.get('state')}, phase={f.get('execution_phase')}, last_event={f.get('last_event')}, guard=**{f.get('guard')}**")
                    if f.get("review_feedback"):
                        L.append(f"  - review_feedback: {f['review_feedback']}")
                else:
                    L.append(f"- run-level: {f.get('reason')} (guard={f.get('guard')})")
        else:
            L.append("- none")
        L.append("")

        L.append("## 6. Artifacts / Deliverable pointers")
        a = r["artifacts"]
        L.append(f"- artifact_refs: {a.get('artifact_refs_count')}")
        for ref in a.get("artifact_refs", [])[:20]:
            L.append(f"  - {ref.get('path')} ({ref.get('bytes')} bytes)")
        L.append(f"- deliverables: {a.get('note')}")
        L.append("")

        L.append("## 7. Repro Commands")
        env = r["repro_env"]
        if env:
            for k, v in env.items():
                L.append(f"- `{k}={v}`")
        else:
            L.append("- (no FIRMA_* env captured)")
        L.append("")

        L.append("## 8. Tool Usage by Role")
        tu = r.get("tool_usage", {})
        by_role = tu.get("by_role", {})
        if by_role:
            for role, tool_counts in by_role.items():
                L.append(f"### {role}")
                for tool_name, count in sorted(tool_counts.items()):
                    L.append(f"- `{tool_name}`: {count}")
                L.append("")
        else:
            L.append("- no tool usage data (from-scratch run or pimesh transport disabled)")
            L.append("")

        L.append("## 9. Tool Policy Checks")
        checks = r.get("tool_policy_checks", [])
        if checks:
            violations_found = False
            for chk in checks:
                violations = chk.get("policy_violations") or []
                if violations:
                    violations_found = True
                status = "OK" if chk.get("ok") else "**POLICY VIOLATION**"
                L.append(f"- task `{chk['task_id']}` ({chk['role']}): {status}")
                for tool_name, count in sorted((chk.get("tool_usage") or {}).items()):
                    prefix = "  - " + ("[FORBIDDEN] " if tool_name in ("edit", "bash", "glob", "grep") else "")
                    L.append(f"{prefix}`{tool_name}`: {count}")
            if violations_found:
                L.append("")
                L.append("> **WARNING:** POLICY VIOLATIONS detected. See details above.")
        else:
            L.append("- no policy checks (no tool usage data available)")
        L.append("")

        L.append("## 10. Turn Usage by Role")
        turn = r.get("turn_usage", {})
        turn_by_role = turn.get("by_role", {})
        if turn_by_role:
            for role, agg in turn_by_role.items():
                L.append(f"### {role}")
                L.append(f"- tasks: {agg.get('tasks', 0)}")
                L.append(f"- turns: {agg.get('turns', 0)}")
                L.append(f"- tool_calls: {agg.get('tool_calls', 0)}")
                warns = agg.get("warnings") or []
                for w in warns:
                    L.append(f"- warning: {w}")
                L.append("")
        else:
            L.append("- no turn usage data (worker logs not available)")
            L.append("")

        if r.get("warnings"):
            L.append("## Warnings (non-fatal)")
            for w in r["warnings"]:
                L.append(f"- {w}")
            L.append("")

        return "\n".join(L)
