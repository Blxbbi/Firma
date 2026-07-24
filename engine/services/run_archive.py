"""
RunArchiver — Phase 1 (Idee D): minimal, self-contained run archiving.

Persists a small archive per run under ``archive/runs/<run_id>/``:
  - manifest.json        (central index)
  - config_snapshot.json (FIRMA_* settings + relevant env)
  - artifact_manifest.json (pointer list into data/artifacts/<run_id>/ — NOT a copy)
  - db_snapshot.json     (slank v1: Run-Record + Task-States + failure_reason + counters)
  - run.log              (per-run FileHandler capture)

Artifacts themselves are NEVER duplicated; the archive only references them.
Retention: keep newest KEEP_LAST_N uncompressed, compress older ones to .tar.gz,
and bound compressed archives by KEEP_COMPRESSED_LAST_N (soft-cap).
"""
import json
import logging
import os
import shutil
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.settings import (
    ARCHIVE_RUNS_DIR,
    ARTIFACT_DIR,
    BASE_DIR,
    KEEP_LAST_N,
    KEEP_COMPRESSED_LAST_N,
    PIMESH_CREWS,
)

logger = logging.getLogger(__name__)


class RunArchiver:
    def __init__(
        self,
        archive_runs_dir: Optional[Path] = None,
        artifact_dir: Optional[Path] = None,
        keep_last_n: int = KEEP_LAST_N,
        keep_compressed_last_n: int = KEEP_COMPRESSED_LAST_N,
    ):
        self.archive_runs_dir = Path(archive_runs_dir or ARCHIVE_RUNS_DIR)
        self.artifact_dir = Path(artifact_dir or ARTIFACT_DIR)
        self.keep_last_n = keep_last_n
        self.keep_compressed_last_n = keep_compressed_last_n
        self._handlers: Dict[str, logging.Handler] = {}

    # ---------------------------------------------------------------- logging
    def attach_run_log_handler(self, run_id: str) -> None:
        """Start capturing this run's logs into archive/runs/<run_id>/run.log."""
        run_dir = self.archive_runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        log_path = run_dir / "run.log"
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        logging.getLogger().addHandler(handler)
        self._handlers[run_id] = handler
        logger.info(f"[Archiver] attached run.log -> {log_path}")

    def detach_run_log_handler(self, run_id: str) -> None:
        handler = self._handlers.pop(run_id, None)
        if handler is not None:
            logging.getLogger().removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass

    # --------------------------------------------------------------- collection
    def _collect_artifact_refs(self, run_id: str) -> List[Dict[str, Any]]:
        refs: List[Dict[str, Any]] = []
        base = self.artifact_dir / run_id
        if not base.exists():
            return refs
        for path in sorted(base.rglob("*")):
            if path.is_file():
                refs.append(
                    {
                        "task_id": path.parent.name,
                        "path": str(path),
                        "bytes": path.stat().st_size,
                    }
                )
        return refs

    def _collect_tool_usage(self, run_id: str) -> Dict[str, Dict[str, int]]:
        """Parse worker.log files under pimesh crew dirs and aggregate tool calls by role.

        Returns: {role: {tool_name: count, ...}, ...}
        """
        usage: Dict[str, Dict[str, int]] = {}
        base = Path(BASE_DIR)

        # Map task_id -> role from the run's tasks (provided by caller)
        # We scan all crew workdirs for this run_id
        for role, crew_rel in PIMESH_CREWS.items():
            crew_dir = base / crew_rel / ".pi" / "work" / run_id
            if not crew_dir.is_dir():
                continue
            for task_dir in sorted(crew_dir.iterdir()):
                if not task_dir.is_dir():
                    continue
                log_path = task_dir / "worker.log"
                if not log_path.is_file():
                    continue
                try:
                    with log_path.open("r", encoding="utf-8", errors="replace") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                obj = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            # tool_execution_start: {"type": "tool_execution_start", "toolName": "read", ...}
                            if (
                                isinstance(obj, dict)
                                and obj.get("type") == "tool_execution_start"
                            ):
                                tool_name = obj.get("toolName") or obj.get("name")
                                if isinstance(tool_name, str):
                                    tool_name = tool_name.strip().lower()
                                    if not tool_name:
                                        continue
                                    role_usage = usage.setdefault(role, {})
                                    role_usage[tool_name] = role_usage.get(tool_name, 0) + 1
                except Exception:
                    continue

        return usage

    def _role_for_task(self, crew_rel: str, task_id: str) -> str:
        """Deterministic role resolution for a worker log.

        - pimesh/coding-crew -> CODER
        - pimesh/reviewing-crew -> REVIEWER
        - pimesh/planning-crew -> load tasks/<task_id>.json and read firma_assignment.role
        - fallback -> UNKNOWN
        """
        crew_name = Path(crew_rel).name
        if crew_name == "coding-crew":
            return "CODER"
        if crew_name == "reviewing-crew":
            return "REVIEWER"
        if crew_name == "planning-crew":
            task_json = Path(BASE_DIR) / crew_rel / ".pi" / "messenger" / "crew" / "tasks" / f"{task_id}.json"
            if task_json.is_file():
                try:
                    data = json.loads(task_json.read_text(encoding="utf-8", errors="replace"))
                    role = ((data.get("firma_assignment") or {}).get("role") or data.get("role"))
                    if isinstance(role, str) and role:
                        return role.upper()
                except Exception:
                    pass
            return "PLANNING_CREW_UNKNOWN"
        return "UNKNOWN"

    def _collect_tool_usage_by_task(
        self, run_id: str
    ) -> Dict[str, Dict[str, int]]:
        """Parse worker.log files and aggregate tool calls by (role, task_id).

        Returns: {"ROLE:task_id": {tool_name: count, ...},
                 ...}
        """
        from engine.services.worker_log_parser import parse_worker_log

        by_task: Dict[str, Dict[str, int]] = {}
        base = Path(BASE_DIR)
        seen_task_dirs: set = set()

        for role, crew_rel in PIMESH_CREWS.items():
            crew_dir = base / crew_rel / ".pi" / "work" / run_id
            if not crew_dir.is_dir():
                continue
            for task_dir in sorted(crew_dir.iterdir()):
                if not task_dir.is_dir():
                    continue
                task_id = task_dir.name
                log_path = task_dir / "worker.log"
                if not log_path.is_file():
                    continue
                # Avoid double-counting when multiple roles share the same crew dir
                task_dir_key = str(task_dir)
                if task_dir_key in seen_task_dirs:
                    continue
                seen_task_dirs.add(task_dir_key)
                actor_role = self._role_for_task(crew_rel, task_id)
                key = f"{actor_role}:{task_id}"
                try:
                    metrics = parse_worker_log(log_path)
                    task_usage = by_task.setdefault(key, {})
                    for tool_name, count in (metrics.tool_calls or {}).items():
                        task_usage[tool_name] = task_usage.get(tool_name, 0) + count
                except Exception:
                    continue

        return by_task

    def _collect_turn_usage_by_task(self, run_id: str) -> Dict[str, Dict[str, Any]]:
        """Parse worker.log files and aggregate turn/tool/metrics by (role, task_id).

        A task may have worker logs in multiple crew dirs (e.g. coder + reviewer).
        We keep them separate by using a role-qualified key so metrics are not
        summed across different roles for the same task_id.
        """
        from engine.services.worker_log_parser import parse_worker_log

        by_task: Dict[str, Dict[str, Any]] = {}
        base = Path(BASE_DIR)
        seen_task_dirs: set = set()

        for role, crew_rel in PIMESH_CREWS.items():
            crew_dir = base / crew_rel / ".pi" / "work" / run_id
            if not crew_dir.is_dir():
                continue
            for task_dir in sorted(crew_dir.iterdir()):
                if not task_dir.is_dir():
                    continue
                task_id = task_dir.name
                log_path = task_dir / "worker.log"
                if not log_path.is_file():
                    continue
                # Avoid double-counting when multiple roles share the same crew dir
                task_dir_key = str(task_dir)
                if task_dir_key in seen_task_dirs:
                    continue
                seen_task_dirs.add(task_dir_key)
                actor_role = self._role_for_task(crew_rel, task_id)
                key = f"{actor_role}:{task_id}"
                metrics = parse_worker_log(log_path)
                data = metrics.to_dict()
                data.setdefault("observed_roles", [])
                if actor_role not in data["observed_roles"]:
                    data["observed_roles"].append(actor_role)
                by_task[key] = data
        return by_task

    def _build_config_snapshot(self, config: Dict[str, Any]) -> Dict[str, Any]:
        snap: Dict[str, Any] = {}
        if config:
            for k, v in config.items():
                if k.startswith("FIRMA") or k in (
                    "app",
                    "transport",
                    "mode",
                    "project_name",
                ):
                    snap[k] = v
        # capture relevant runtime env (never overwrite values already in config)
        env_keys = (
            "FIRMA_TRANSPORT",
            "FIRMA_APP",
            "FIRMA_MODE",
            "SESSION_MODE",
            "FIRMA_PROCESS_MODE",
            "MAX_CONCURRENT_SPAWNS",
            "FIRMA_PERSONA_ID",
            "FIRMA_ARCHIVE_KEEP_LAST_N",
            "FIRMA_ARCHIVE_KEEP_COMPRESSED_LAST_N",
        )
        for k in env_keys:
            if k in os.environ:
                snap.setdefault(k, os.environ[k])
        return snap

    # ----------------------------------------------------------------- archive
    async def archive_run(
        self,
        run_id: str,
        controller,
        config: Dict[str, Any],
        store=None,
    ) -> Dict[str, Any]:
        """Write the run archive. Must never raise (archiving is best-effort)."""
        run_dir = self.archive_runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        status = await controller.get_run_status(run_id)
        summary: Dict[str, Any] = {}
        try:
            summary = await controller.get_run_summary(run_id) or {}
        except Exception as exc:  # defensive: archiving must not crash the run
            logger.warning(f"[Archiver] get_run_summary failed: {exc}")

        started_at = summary.get("started_at") or status.get("started_at")
        terminal_state = summary.get("terminal_state") or status.get("status")
        task_summary = summary.get("task_summary", [])
        failure_reason = summary.get("failure_reason") or status.get("failure_reason")
        summary_counters = summary.get("summary_counters", {})

        app = (config or {}).get("app") or os.environ.get("FIRMA_APP")
        transport = (
            (config or {}).get("FIRMA_TRANSPORT")
            or (config or {}).get("transport")
            or os.environ.get("FIRMA_TRANSPORT")
            or (status or {}).get("transport")
        )

        artifact_refs = self._collect_artifact_refs(run_id)
        config_snapshot = self._build_config_snapshot(config or {})

        # Phase 7 (Idee A): collect tool usage from worker.log files for audit
        tool_usage_by_task = self._collect_tool_usage_by_task(run_id)
        turn_usage_by_task = self._collect_turn_usage_by_task(run_id)

        manifest = {
            "run_id": run_id,
            "app": app,
            "transport": transport,
            "started_at": started_at,
            "terminal_state": terminal_state,
            "task_summary": task_summary,
            "artifact_refs": artifact_refs,
            "tool_usage_by_task": tool_usage_by_task,
            "turn_usage_by_task": turn_usage_by_task,
            "logs_path": str(run_dir / "run.log"),
            "db_snapshot_path": str(run_dir / "db_snapshot.json"),
            "config_snapshot": config_snapshot,
            "archived_at": datetime.now(timezone.utc).isoformat(),
        }

        # Phase 2 (Idee A): if this run used project ingest, archive the baseline
        # manifest and record workspace/scope pointers for later drift audit.
        try:
            from engine.services.ingest_context import (
                get_ingest,
                get_all_task_scopes,
                clear_ingest,
            )
            ing = get_ingest(run_id)
            if ing:
                baseline_src = ing["baseline_path"]
                if os.path.exists(baseline_src):
                    shutil.copy2(baseline_src, run_dir / "baseline_manifest.json")
                    manifest["baseline_manifest"] = "baseline_manifest.json"
                manifest["workspace_root"] = ing["workspace_root"]
                manifest["scope_summary"] = get_all_task_scopes(run_id)
                # Phase 3 (Idee B): copy the Researcher's read-only briefing into the archive
                research_dir = os.path.join(os.path.dirname(ing["workspace_root"]), "research")
                brief_src = os.path.join(research_dir, "brief.md")
                if os.path.exists(brief_src):
                    shutil.copy2(brief_src, run_dir / "research_brief.md")
                    manifest["research_brief"] = "research_brief.md"
                clear_ingest(run_id)
        except Exception as exc:
            logger.warning(f"[Archiver] ingest archive enrichment failed (non-fatal): {exc}")

        self._write_json(run_dir / "manifest.json", manifest)
        self._write_json(run_dir / "config_snapshot.json", config_snapshot)
        self._write_json(run_dir / "artifact_manifest.json", artifact_refs)
        db_snap = {
            "run_id": run_id,
            "terminal_state": terminal_state,
            "started_at": started_at,
            "task_summary": task_summary,
            "failure_reason": failure_reason,
            "summary_counters": summary_counters,
        }
        self._write_json(run_dir / "db_snapshot.json", db_snap)

        # Phase 4 (Idee C): produce a read-only audit report from the freshly
        # written archive + DB. Best-effort and NON-FATAL: archiving must never
        # crash or block the run because the auditor failed.
        try:
            from engine.services.auditor import RunAuditor
            await RunAuditor().write_report(run_id, run_dir, controller)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[Archiver] auditor report failed (non-fatal): {exc}")

        logger.info(
            f"[Archiver] archived run {run_id} -> {run_dir} "
            f"({len(artifact_refs)} artifact refs)"
        )
        # retention enforcement runs pro run (deterministic, no extra job)
        self.enforce_retention()
        return manifest

    @staticmethod
    def _write_json(path: Path, data: Any) -> None:
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # --------------------------------------------------------------- retention
    def enforce_retention(self) -> None:
        self.archive_runs_dir.mkdir(parents=True, exist_ok=True)
        runs = [p for p in self.archive_runs_dir.iterdir() if p.is_dir()]
        runs.sort(key=lambda p: p.stat().st_mtime)
        if len(runs) > self.keep_last_n:
            for old in runs[: len(runs) - self.keep_last_n]:
                self._compress_and_remove(old)
        # soft-cap on compressed archives
        targz = sorted(
            self.archive_runs_dir.glob("*.tar.gz"),
            key=lambda p: p.stat().st_mtime,
        )
        if len(targz) > self.keep_compressed_last_n:
            for old in targz[: len(targz) - self.keep_compressed_last_n]:
                try:
                    old.unlink()
                except OSError:
                    pass

    def _compress_and_remove(self, run_dir: Path) -> None:
        archive_path = run_dir.with_suffix(".tar.gz")
        try:
            with tarfile.open(archive_path, "w:gz") as tar:
                tar.add(run_dir, arcname=run_dir.name)
            shutil.rmtree(run_dir)
            logger.info(f"[Archiver] compressed old run -> {archive_path}")
        except Exception as exc:
            logger.warning(f"[Archiver] compression failed for {run_dir}: {exc}")
