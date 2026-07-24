"""
run_pi_mesh.py — Dedicated PiMesh Entrypoint (Firma-Kernel + pi-harness Worker-Mesh).

Startet den Firma-Kernel mit PiMeshTransport und einen PiMeshReceiverLoop, der
pi-messenger's on-disk Task-State pollt (KEIN Tool/CLI-Aufruf in Firma-Python):

  PiMeshTransport.dispatch()  -> schreibt <crew-cwd>/.pi/messenger/crew/tasks/task-N.json(+md)
  Firma (Orchestrator)        -> PiProvider.spawn_worker startet `pi --mode json` im Crew-Dir
  Crew-Worker (LLM-Agent)     -> liest task-N.md, schreibt Dateien + worker_response.<task_id>.response.json
  PiMeshReceiverLoop          -> scannt crew-cwd, bei worker_response-Praesenz:
                                 inline content -> WorkerResponse.model_validate -> publish_response

Completion-Signal = PRAESENZ der worker_response-Datei (kein task.done noetig).
Der Orchestrator konsumiert wie gewohnt transport.poll() (blind, envelope-flattening).
KEINE Kernel-Aenderung noetig. Rollback via FIRMA_TRANSPORT=in-process (run_snake.py).
"""
import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from engine.settings import (
    BASE_DIR, DB_DIR, ARTIFACT_DIR, FIRMA_TRANSPORT, PIMESH_CREWS, PIMESH_MODELS, REVIEWER_IS_DUMMY,
    FIRMA_MODE, SESSION_DIR, REVIEWER_DUMMY_REJECT_ONCE, SESSION_MODE, MAX_SESSION_DISK_MB_PER_RUN, PERSONA_ID, MAX_CONCURRENT_SPAWNS,
)
from engine.transport.pi_mesh_transport import PiMeshTransport, WORKER_RESPONSE_SUFFIX
from engine.providers.pi_provider import PiProvider
from engine.models import WorkerResponse, TaskEvent, AssignedRole
from engine.session_registry import SessionRegistry
from engine.services.workspace_materializer import materialize_to_workspace as _materialize_to_workspace

_PLACEHOLDER_TIMESTAMP_UTC = "$(date -u +%Y-%m-%dT%H:%M:%S.%N+00:00)"
_PLACEHOLDER_TIMESTAMP_LOCAL = "$(date +%Y-%m-%dT%H:%M:%S.%N)"


def _repair_worker_response_timestamp(worker_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Lightweight repair before schema validation.

    Known failure mode: REVIEWER emits a literal shell placeholder as `timestamp`
    (e.g. `$(date -u +%Y-%m-%dT%H:%M:%S.%N+00:00)`). Pydantic rejects it as invalid datetime.
    Instead of hard-failing, replace it with a kernel-generated UTC ISO timestamp.
    """
    ts = worker_payload.get("timestamp") if isinstance(worker_payload, dict) else None
    if isinstance(ts, str) and ts in {_PLACEHOLDER_TIMESTAMP_UTC, _PLACEHOLDER_TIMESTAMP_LOCAL}:
        worker_payload = dict(worker_payload)
        worker_payload["timestamp"] = datetime.now(timezone.utc).isoformat()
        logger.warning("[Receiver] Repaired literal shell placeholder timestamp to UTC now")
    return worker_payload


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("run_pi_mesh")

DEBUG_RECEIVER_RECOVERY = os.environ.get("FIRMA_DEBUG_RECEIVER_RECOVERY") == "1"


def _try_unescape_json(text: str):
    """Versucht double-escaped JSON zu reparieren ({\n  \"key\": ...} -> echtes JSON).

    Manche Modelle schreiben die Response mit literalen Backslash-Escapes (\\n, \\")
    statt echtem JSON. unicode_escape macht daraus valides JSON.
    """
    try:
        return json.loads(text.encode("utf-8").decode("unicode_escape"))
    except Exception:
        return None


def _scrub_retry_response(crew_cwd: str, task_id: str) -> bool:
    """Phase 6.2 Fix 1: loescht die stale worker_response-Datei vor einem CODER-Retry.

    Ohne das glaubt der Retry-Coder (via Session-Kontinuitaet + Datei auf Disk),
    die Aufgabe sei bereits abgeschlossen, und verweigert den Retry -> Loop.
    Gibt True zurueck, wenn eine Datei geloescht wurde.
    """
    worker_dir = os.path.join(crew_cwd, ".pi", "messenger", "crew")
    stale = os.path.join(worker_dir, f"worker_response.{task_id}{WORKER_RESPONSE_SUFFIX}")
    if os.path.exists(stale):
        try:
            os.remove(stale)
            logger.info('[pimesh] removed stale worker_response for retry %s', task_id)
            return True
        except OSError as e:
            logger.warning('[pimesh] could not remove stale response %s: %s', stale, e)
    return False


class PiMeshReceiverLoop:
    """Pollt pi-messenger's on-disk Task-State und uebersetzt in WorkerResponse.

    file-based, polling-only, kein pi_messenger-Tool-Aufruf.
    """

    def __init__(
        self,
        transport: PiMeshTransport,
        crew_cwds: Dict[str, str],
        project_root: str,
        interval: float = 1.0,
        expected_run_id: Optional[str] = None,
        task_done_events: Optional[Dict[tuple, asyncio.Event]] = None,
        task_assigned_at: Optional[Dict[str, Tuple[str, float]]] = None,
    ):
        self.transport = transport
        self.crew_cwds = crew_cwds
        self.project_root = project_root
        self.interval = interval
        self.expected_run_id = expected_run_id
        self.task_done_events = task_done_events or {}
        self.task_assigned_at = task_assigned_at or {}
        self._consumed: set = set()
        self._guarded_tasks: set = set()
        self._agent_end_seen: Dict[str, bool] = {}
        self.NO_PROGRESS_TIMEOUT_S = 120.0
        self.running = False

    # ------------------------------------------------------------------ helpers
    def _crew_cwd(self, role: str) -> str:
        return os.path.join(self.project_root, self.crew_cwds.get(role, PiMeshTransport.ROLE_TO_CREW[role]))

    def _tasks_dir(self, crew_cwd: str) -> str:
        return os.path.join(crew_cwd, ".pi", "messenger", "crew", "tasks")

    def _worker_dir(self, crew_cwd: str) -> str:
        """Das Verzeichnis, in dem der Worker artefakte + response schreibt
        (neben `tasks/`; der Worker arbeitet natuerlich von hier)."""
        return os.path.join(crew_cwd, ".pi", "messenger", "crew")

    @staticmethod
    def _safe_path(crew_cwd: str, rel: str) -> Optional[str]:
        """Relative, normalisierte Pfade erlauben; absolut/`..` blocken (Security Boundary)."""
        if not rel or rel.startswith("/") or rel.startswith("\\") or ".." in rel:
            return None
        return os.path.join(crew_cwd, rel)

    def _inline_content(self, crew_cwd: str, worker_payload: Dict[str, Any]) -> tuple:
        """Liest Artefakt-Inhalte aus dem Crew-cwd und fuellt content inline.

        Gibt (payload, unsafe) zurueck. unsafe=True, wenn ein Artefakt-Pfad ausserhalb
        des Crew-cwd liegt (absolute Pfade / '..') -> Security Boundary (Invariante 7).
        """
        unsafe = False
        artifacts = worker_payload.get("artifacts") or []
        for art in artifacts:
            if not isinstance(art, dict):
                continue
            action = art.get("action")
            if action in ("CREATE", "UPDATE"):
                fp = self._safe_path(self._worker_dir(crew_cwd), art.get("path", ""))
                if fp is None:
                    unsafe = True
                    art["content"] = None
                    continue
                # Robust: behalte inline content, falls der Worker es schon gesetzt hat;
                # fuelle nur aus Datei, wenn content fehlt (null). Datei = Quelle der Wahrheit.
                if art.get("content") is None:
                    if os.path.isfile(fp):
                        try:
                            with open(fp, "r", encoding="utf-8") as f:
                                content = f.read()
                            art["content"] = content
                            # Phase 2 (Idee A) Step3.3: workspace tree is the source of
                            # truth for the scope verifier -> materialize the CODER edit there.
                            _materialize_to_workspace(worker_payload.get("run_id"), art.get("path"), content)
                        except Exception as e:
                            logger.warning(f"[Receiver] Cannot read {fp}: {e}")
                            art["content"] = None
                    else:
                        art["content"] = None
            elif action == "DELETE":
                art["content"] = None
        return worker_payload, unsafe

    def _inline_plan_draft(self, crew_cwd: str, task_id: str, worker_payload: Dict[str, Any]) -> None:
        """Recover a Planner's structured plan from a side-file (plan_draft.<task_id>.json
        or plan_draft.json) when the worker_response JSON omits the ``plan_draft`` field.

        Why: Planner workers frequently write the plan to a side-file (source of truth on
        disk) instead of embedding the large structured JSON in the response. Without this,
        the Guardian receives ``plan_draft=None`` -> creates NO CODER tasks -> run completes
        with only RESEARCHER+PLANNER. Deterministic, LLM-compliance-independent recovery.
        """
        if not isinstance(worker_payload, dict):
            return
        if worker_payload.get("event") != TaskEvent.PLAN_SUBMITTED.value:
            return
        if worker_payload.get("plan_draft"):
            return
        worker_dir = self._worker_dir(crew_cwd)
        side = os.path.join(worker_dir, f"plan_draft.{task_id}.json")
        if not os.path.isfile(side):
            # Fallback: some workers write plan_draft.json without task_id suffix.
            side = os.path.join(worker_dir, "plan_draft.json")
            if not os.path.isfile(side):
                return
        try:
            with open(side, "r", encoding="utf-8") as f:
                data = json.load(f)
            worker_payload["plan_draft"] = data
            logger.info(f"[Receiver] Recovered plan_draft from side-file for {task_id}")
        except Exception as e:
            logger.warning(f"[Receiver] Cannot parse plan side-file {side}: {e}")

    def _response_artifacts_pending(self, crew_cwd, wp) -> bool:
        """True wenn ein CREATE/UPDATE-Artefakt noch nicht auf persistente Disk liegt.

        Reihenfolge:
        1. `data/artifacts/<run_id>/<task_id>/` (ARTIFACT_DIR, Artefakt-Store)
        2. Worker-Dir (Fallback für CODER-Inline, bevor der Store gefüllt ist)

        Das Modell schreibt die worker_response-Datei oft mehrfach um (je nach Datei,
        die es gerade erzeugt hat). Solange kein referenziertes Artefakt auf persistente
        Disk geschrieben wurde, wird der Scan deferiert, um Race-Conditions + falsche
        Artifact-Contract-Violations zu meiden.
        """
        if not isinstance(wp, dict):
            return False
        arts = wp.get("artifacts") or []
        worker_dir = self._worker_dir(crew_cwd)
        run_id = wp.get("run_id")
        task_id = wp.get("task_id")
        for art in arts:
            if not isinstance(art, dict):
                continue
            if art.get("action") not in ("CREATE", "UPDATE"):
                continue
            p = art.get("path", "")
            if not p:
                continue
            # 1. Artefakt-Store (ARTIFACT_DIR/<run_id>/<task_id>/<path>)
            store_path = None
            if run_id and task_id:
                candidate = os.path.join(ARTIFACT_DIR, run_id, task_id, p)
                if os.path.isfile(candidate):
                    continue  # vorhanden -> nicht pending
            # 2. Worker-Dir (Fallback)
            safe = self._safe_path(worker_dir, p)
            if safe is None:
                # Unsicherer Pfad -> vom _inline_content behandelt, nicht defer-en.
                continue
            if not os.path.isfile(safe):
                return True
        return False

    # ------------------------------------------------------------------ guards
    def _worker_log_path(self, crew_cwd: str, task_id: str) -> Optional[str]:
        if not self.expected_run_id:
            return None
        return os.path.join(crew_cwd, '.pi', 'work', self.expected_run_id, task_id, 'worker.log')

    def _has_agent_end(self, crew_cwd: str, task_id: str) -> bool:
        if task_id in self._agent_end_seen:
            return self._agent_end_seen[task_id]
        log_path = self._worker_log_path(crew_cwd, task_id)
        if not log_path or not os.path.isfile(log_path):
            self._agent_end_seen[task_id] = False
            return False
        try:
            with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if obj.get('type') == 'agent_end':
                        self._agent_end_seen[task_id] = True
                        return True
        except Exception:
            pass
        self._agent_end_seen[task_id] = False
        return False

    def _has_write_progress(self, crew_cwd: str, task_id: str) -> bool:
        log_path = self._worker_log_path(crew_cwd, task_id)
        if not log_path or not os.path.isfile(log_path):
            return False
        try:
            with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    t = obj.get('type')
                    if t in ('message_start', 'message_end', 'message_update'):
                        msg = obj.get('message', {})
                        for c in (msg.get('content') or []):
                            if c.get('type') == 'toolCall' and c.get('name') == 'write':
                                return True
                    if t in ('tool_execution_start', 'tool_execution_end'):
                        if obj.get('tool_name') == 'write' or obj.get('name') == 'write':
                            return True
        except Exception:
            pass
        return False

    def _publish_system_failure(self, task_id: str, event: str, reason: str, role: str = 'SYSTEM') -> Optional[Dict[str, Any]]:
        key = (self.expected_run_id, task_id, None)
        if key in self._consumed or task_id in self._guarded_tasks:
            return None
        self._guarded_tasks.add(task_id)
        payload = {
            'protocol_version': '1.0',
            'message_id': f"{event.lower()}-{task_id}-{uuid.uuid4().hex}",
            'task_id': task_id,
            'run_id': self.expected_run_id,
            'state_revision': None,
            'event': event,
            'sender_role': role,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'logs': reason,
            'artifacts': None,
            'plan_draft': None,
        }
        self._consumed.add(key)
        return {
            'role': role,
            'payload': payload,
            'correlation_id': task_id,
        }

    def _schema_fail(self, raw: Dict[str, Any], error: str) -> Dict[str, Any]:
        """Kanonischer Struktur-Bruch -> SUBMISSION_INVALID_SCHEMA (kein Repair)."""
        wp = raw.get("payload", raw) if isinstance(raw, dict) else {}
        return {
            "protocol_version": "1.0",
            "message_id": wp.get("message_id") or "missing",
            "task_id": wp.get("task_id"),
            "run_id": wp.get("run_id"),
            "state_revision": wp.get("state_revision"),
            "event": "SUBMISSION_INVALID_SCHEMA",
            "sender_role": wp.get("sender_role", "SYSTEM"),
            "timestamp": wp.get("timestamp"),
            "logs": f"Schema validation error: {error}",
            "artifacts": None,
            "plan_draft": None,
        }

    def _recover_researcher_response(self, crew_cwd: str) -> None:
        """Fallback: wenn der RESEARCHER `research/brief.md` geschrieben hat,
        aber KEINE `worker_response.<task_id>.response.json` erzeugt hat,
        generiere eine synthetische Response-Datei mit event=RESEARCH_COMPLETE.

        Dies ist eine Defense-in-Depth-Massnahme fuer das bekannte LLM-Verhalten,
        die Response-Datei zu vergessen (Bug F5).
        """
        run_id = self.expected_run_id
        if not run_id:
            if DEBUG_RECEIVER_RECOVERY:
                logger.info('[Receiver-Recovery] SKIP missing_run_id')
            return

        worker_dir = self._worker_dir(crew_cwd)
        brief_path = os.path.join(worker_dir, 'research', 'brief.md')
        base_work = os.path.join(crew_cwd, '.pi', 'work', run_id)

        # --- Debug-Logging (opt-in via FIRMA_DEBUG_RECEIVER_RECOVERY=1) ---
        if DEBUG_RECEIVER_RECOVERY:
            logger.info(
                '[Receiver-Recovery] scan start: crew_cwd=%s expected_run_id=%s worker_dir=%s base_work=%s',
                crew_cwd, run_id, worker_dir, base_work,
            )

        if not os.path.isfile(brief_path):
            if DEBUG_RECEIVER_RECOVERY:
                logger.info('[Receiver-Recovery] SKIP brief_exists=False brief_path=%s', brief_path)
            return

        if not os.path.isdir(base_work):
            if DEBUG_RECEIVER_RECOVERY:
                logger.info('[Receiver-Recovery] SKIP base_work_missing base_work=%s', base_work)
            return

        worker_dir = self._worker_dir(crew_cwd)
        for task_id in os.listdir(base_work):
            task_work = os.path.join(base_work, task_id)
            if not os.path.isdir(task_work):
                if DEBUG_RECEIVER_RECOVERY:
                    logger.info('[Receiver-Recovery] SKIP not_a_task_dir task_id=%s task_work=%s', task_id, task_work)
                continue

            resp_file = f'worker_response.{task_id}{WORKER_RESPONSE_SUFFIX}'
            resp_path = os.path.join(worker_dir, resp_file)
            response_exists = os.path.exists(resp_path)
            project_dir = os.path.join(task_work, 'project')
            project_exists = os.path.isdir(project_dir)

            if DEBUG_RECEIVER_RECOVERY:
                logger.info(
                    '[Receiver-Recovery] candidate_recovery: run_id=%s task_id=%s role=RESEARCHER '
                    'expected_worker_dir=%s brief_exists=True response_exists=%s project_exists=%s',
                    run_id, task_id, worker_dir, response_exists, project_dir,
                )

            if response_exists:
                if DEBUG_RECEIVER_RECOVERY:
                    logger.info('[Receiver-Recovery] SKIP response_exists task_id=%s', task_id)
                continue

            if not project_exists:
                # Project-Verzeichnis ist fuer Recovery nicht zwingend noetig,
                # da wir nur die worker_response aus brief.md synthetisieren.
                # Erstellen falls nicht vorhanden.
                try:
                    os.makedirs(project_dir, exist_ok=True)
                except Exception:
                    pass

            # --- Race-Guard: Recovery NUR fuer echte RESEARCHER-Tasks ---
            task_json_path = os.path.join(worker_dir, 'tasks', f'{task_id}.json')
            is_researcher_task = False
            try:
                with open(task_json_path, 'r', encoding='utf-8') as tf:
                    task_data = json.load(tf)
                role = (
                    task_data.get('role')
                    or (task_data.get('firma_assignment') or {}).get('role')
                )
                if role == 'RESEARCHER':
                    is_researcher_task = True
            except Exception:
                pass
            if not is_researcher_task:
                if DEBUG_RECEIVER_RECOVERY:
                    logger.info(
                        '[Receiver-Recovery] SKIP not_researcher task_id=%s role=%s',
                        task_id, role,
                    )
                continue
            # ------------------------------------------------------------

            if DEBUG_RECEIVER_RECOVERY:
                logger.info(
                    '[Receiver-Recovery] RECOVERY_FIRE: brief_path=%s response_path=%s',
                    brief_path, resp_path,
                )

            # Read current state_revision from the task file to avoid stale-revision rejection
            state_revision = 0
            task_json_path = os.path.join(worker_dir, 'tasks', f'{task_id}.json')
            try:
                with open(task_json_path, 'r', encoding='utf-8') as tf:
                    task_data = json.load(tf)
                # state_revision can be nested under firma_assignment (pi-messenger schema)
                state_revision = int(
                    task_data.get('state_revision')
                    or (task_data.get('firma_assignment') or {}).get('state_revision', 0)
                )
            except Exception:
                pass

            now = datetime.now(timezone.utc).isoformat()
            synthetic = {
                'protocol_version': '1.0',
                'message_id': f'{task_id}-recover-{uuid.uuid4().hex[:8]}',
                'task_id': task_id,
                'run_id': run_id,
                'state_revision': state_revision,
                'event': 'RESEARCH_COMPLETE',
                'sender_role': 'RESEARCHER',
                'artifacts': [{'path': 'research/brief.md', 'action': 'CREATE', 'content': None}],
                'timestamp': now,
                'logs': 'RECOVERED_BY_KERNEL=true; recovered from research/brief.md (worker_response missing)',
            }
            try:
                with open(resp_path, 'w', encoding='utf-8') as f:
                    json.dump(synthetic, f, indent=2, ensure_ascii=False)
                logger.warning(
                    '[Receiver] Recovered missing RESEARCHER worker_response from research/brief.md '
                    '(run_id=%s, task_id=%s)',
                    run_id, task_id,
                )
            except Exception as e:
                logger.warning('[Receiver] Cannot write recovered response for %s: %s', task_id, e)

    # ------------------------------------------------------------------ scan
    def scan_once(self) -> List[Dict[str, Any]]:
        """Ein Scan-Zyklus. Gibt Liste von {role, payload, correlation_id} zurueck.

        Completion-Signal = PRAESENZ der worker_response.<task_id>.response.json im
        Crew-cwd (NICHT task.status==done). Der Worker schreibt diese Datei als letzten
        Schritt; Firma braucht keinen task.done-Call (PiProvider-Spawn, kein Mesh).
        """
        out: List[Dict[str, Any]] = []
        for role in self.crew_cwds:
            crew_cwd = self._crew_cwd(role)
            worker_dir = self._worker_dir(crew_cwd)
            if not os.path.isdir(worker_dir):
                continue
            for fn in os.listdir(worker_dir):
                if not fn.startswith("worker_response.") or not fn.endswith(WORKER_RESPONSE_SUFFIX):
                    continue
                # Dateiname: worker_response.<task_id>.response.json
                task_id = fn[len("worker_response."):-len(WORKER_RESPONSE_SUFFIX)]
                if not task_id:
                    continue

                resp_path = os.path.join(worker_dir, fn)
                try:
                    with open(resp_path, "r", encoding="utf-8") as f:
                        raw_text = f.read()
                    try:
                        raw = json.loads(raw_text)
                    except json.JSONDecodeError:
                        # Defensive: doppelt-escaped JSON ({\\n  \\"key\": ...) reparieren.
                        repaired = _try_unescape_json(raw_text)
                        if repaired is None:
                            logger.debug(f"[Receiver] partial/invalid JSON {resp_path}; retry later")
                            continue
                        raw = repaired
                        logger.warning(f"[Receiver] Recovered double-escaped JSON for {task_id}")
                except Exception as e:
                    logger.warning(f"[Receiver] Cannot read {resp_path}: {e}")
                    continue

                wp = raw.get("payload", raw) if isinstance(raw, dict) else raw
                run_id = wp.get("run_id") if isinstance(wp, dict) else None
                state_revision = wp.get("state_revision") if isinstance(wp, dict) else None
                # P3 fix: stale cross-run responses (gleiche task_id, andere run_id)
                # duerfen diesen Run NICHT vergiften. Vorgaenger-Runs lassen alte
                # worker_response-Dateien im crew-cwd zurueck; ohne run_id-Check
                # wuerde die echte Antwort als Duplikat (selber key) dropped.
                if self.expected_run_id is not None and run_id is not None and run_id != self.expected_run_id:
                    logger.debug(
                        "[Receiver] skip stale response for other run (got=%s, expected=%s): %s",
                        run_id, self.expected_run_id, resp_path,
                    )
                    continue
                key = (run_id, task_id, state_revision)
                if key in self._consumed:
                    continue

                # Defer: referenzierte Artefakt-Dateien noch nicht auf Disk?
                # (Worker schreibt die Response-Datei mehrfach um -> Race vermeiden)
                if self._response_artifacts_pending(crew_cwd, wp):
                    logger.debug(f"[Receiver] Defer {task_id} (rev {state_revision}): artifacts not on disk yet")
                    continue

                # Defer: Planner may emit plan_draft as a side-file (plan_draft.<task_id>.json
                # or plan_draft.json) that is not on disk yet when the response is scanned (race).
                # Recover it deterministically below; if the side-file is missing, defer and re-scan.
                if wp.get("event") == TaskEvent.PLAN_SUBMITTED.value and not wp.get("plan_draft"):
                    worker_dir_for_plan = self._worker_dir(crew_cwd)
                    has_plan_draft = (
                        os.path.isfile(os.path.join(worker_dir_for_plan, f"plan_draft.{task_id}.json"))
                        or os.path.isfile(os.path.join(worker_dir_for_plan, "plan_draft.json"))
                    )
                    if not has_plan_draft:
                        logger.debug(f"[Receiver] Defer {task_id}: plan_draft side-file not on disk yet")
                        continue

                worker_payload = wp
                worker_payload, unsafe = self._inline_content(crew_cwd, worker_payload)
                # Phase: recover plan_draft from side-file (plan_draft.<task_id>.json) if
                # the worker omitted it from the response field (common LLM behavior).
                self._inline_plan_draft(crew_cwd, task_id, worker_payload)

                # Repair known worker bug: literal shell placeholder in `timestamp`.
                worker_payload = _repair_worker_response_timestamp(worker_payload)

                if unsafe:
                    validated = self._schema_fail(raw, "artifact path escapes crew cwd (absolute or '..')")
                    logger.warning(f"[Receiver] Security Boundary: rejected {task_id} (unsafe artifact path)")
                    self._consumed.add(key)
                    # Kernel-generierte, eindeutige message_id (Idempotency-Key).
                    # Der Worker liefert NICHT verlaesslich eine unique id (Placeholder-Kopie!)
                    validated["message_id"] = f"{task_id}-{uuid.uuid4().hex}"
                    out.append({
                        "role": validated.get("sender_role", "SYSTEM"),
                        "payload": validated,
                        "correlation_id": task_id,
                    })
                    continue

                try:
                    validated = WorkerResponse.model_validate(worker_payload).model_dump()
                except Exception as e:
                    validated = self._schema_fail(raw, str(e))
                    logger.warning(f"[Receiver] Schema violation for {task_id}: {e}")

                self._consumed.add(key)
                # Kernel-generierte, eindeutige message_id (Idempotency-Key).
                # Verhindert UNIQUE-Constraint-Crash bei Worker-Placeholder-IDs.
                validated["message_id"] = f"{task_id}-{uuid.uuid4().hex}"
                out.append({
                    "role": validated.get("sender_role", "SYSTEM"),
                    "payload": validated,
                    "correlation_id": task_id,
                })
                logger.info(f"[Receiver] Prepared WorkerResponse for {task_id} (event={validated.get('event')})")
        # Fallback: RESEARCHER hat brief.md geschrieben, aber keine worker_response
        for role in self.crew_cwds:
            crew_cwd = self._crew_cwd(role)
            self._recover_researcher_response(crew_cwd)

        # Nach Recovery nochmal scannen, damit geschriebene worker_response-Dateien
        # im selben Scan-Zyklus gefunden und publiziert werden.
        for role in self.crew_cwds:
            crew_cwd = self._crew_cwd(role)
            worker_dir = self._worker_dir(crew_cwd)
            if not os.path.isdir(worker_dir):
                continue
            for fn in os.listdir(worker_dir):
                if not fn.startswith("worker_response.") or not fn.endswith(WORKER_RESPONSE_SUFFIX):
                    continue
                task_id = fn[len("worker_response."):-len(WORKER_RESPONSE_SUFFIX)]
                if not task_id:
                    continue
                resp_path = os.path.join(worker_dir, fn)
                try:
                    with open(resp_path, "r", encoding="utf-8") as f:
                        raw_text = f.read()
                    try:
                        raw = json.loads(raw_text)
                    except json.JSONDecodeError:
                        repaired = _try_unescape_json(raw_text)
                        if repaired is None:
                            continue
                        raw = repaired
                        logger.warning(f"[Receiver] Recovered double-escaped JSON for {task_id}")
                except Exception as e:
                    logger.warning(f"[Receiver] Cannot read {resp_path}: {e}")
                    continue

                wp = raw.get("payload", raw) if isinstance(raw, dict) else raw
                run_id = wp.get("run_id") if isinstance(wp, dict) else None
                state_revision = wp.get("state_revision") if isinstance(wp, dict) else None
                if self.expected_run_id is not None and run_id is not None and run_id != self.expected_run_id:
                    continue
                key = (run_id, task_id, state_revision)
                if key in self._consumed:
                    continue

                if self._response_artifacts_pending(crew_cwd, wp):
                    continue
                if (wp.get("event") == TaskEvent.PLAN_SUBMITTED.value
                        and not wp.get("plan_draft")
                        and not os.path.isfile(os.path.join(self._worker_dir(crew_cwd), f"plan_draft.{task_id}.json"))):
                    continue

                worker_payload = wp
                worker_payload, unsafe = self._inline_content(crew_cwd, worker_payload)
                self._inline_plan_draft(crew_cwd, task_id, worker_payload)

                # Repair known worker bug: literal shell placeholder in `timestamp`.
                worker_payload = _repair_worker_response_timestamp(worker_payload)

                if unsafe:
                    validated = self._schema_fail(raw, "artifact path escapes crew cwd (absolute or '..')")
                    logger.warning(f"[Receiver] Security Boundary: rejected {task_id} (unsafe artifact path)")
                    self._consumed.add(key)
                    validated["message_id"] = f"{task_id}-{uuid.uuid4().hex}"
                    out.append({
                        "role": validated.get("sender_role", "SYSTEM"),
                        "payload": validated,
                        "correlation_id": task_id,
                    })
                    continue

                try:
                    validated = WorkerResponse.model_validate(worker_payload).model_dump()
                except Exception as e:
                    validated = self._schema_fail(raw, str(e))
                    logger.warning(f"[Receiver] Schema violation for {task_id}: {e}")

                self._consumed.add(key)
                validated["message_id"] = f"{task_id}-{uuid.uuid4().hex}"
                out.append({
                    "role": validated.get("sender_role", "SYSTEM"),
                    "payload": validated,
                    "correlation_id": task_id,
                })
                logger.info(f"[Receiver] Prepared WorkerResponse for {task_id} (event={validated.get('event')})")

        # --- Guards: fail-fast + no-progress ---
        now = time.time()
        for task_id, (role, assigned_at) in list(self.task_assigned_at.items()):
            if task_id in self._guarded_tasks:
                continue
            crew_cwd = self._crew_cwd(role)
            worker_dir = self._worker_dir(crew_cwd)
            resp_file = os.path.join(worker_dir, f"worker_response.{task_id}{WORKER_RESPONSE_SUFFIX}")
            if os.path.isfile(resp_file):
                self.task_assigned_at.pop(task_id, None)
                continue

            fail = None
            if self._has_agent_end(crew_cwd, task_id):
                fail = (
                    'TASK_FAILED',
                    'WORKER_EXITED_WITHOUT_SUBMISSION: agent_end detected in worker.log without worker_response.',
                    role,
                )
            elif now - assigned_at > self.NO_PROGRESS_TIMEOUT_S and not self._has_write_progress(crew_cwd, task_id):
                fail = (
                    'WORKER_TIMEOUT',
                    f'NO_PROGRESS: no worker_response or write tool call within {self.NO_PROGRESS_TIMEOUT_S}s.',
                    role,
                )
            if fail:
                event, reason, sender_role = fail
                synthetic = self._publish_system_failure(task_id, event, reason, role=sender_role)
                if synthetic:
                    out.append(synthetic)
                    logger.warning(f"[Receiver] Guard {event} for {task_id} ({sender_role}): {reason}")
        return out

    def _signal_task_done(self, payload: Dict[str, Any]) -> None:
        """Signalisiert der Spawn-Loop, dass die Response fuer eine Task publiziert wurde.

        Wird nach `publish_response()` aufgerufen und setzt das zugehoerige `task_done_event`.
        """
        wp = payload or {}
        _tid = wp.get("task_id")
        _rev = wp.get("state_revision")
        _role = wp.get("sender_role")
        if _tid is not None and _rev is not None and _role:
            _key = (_tid, _rev, _role)
            _ev = self.task_done_events.get(_key)
            if _ev is not None and not _ev.is_set():
                _ev.set()
                logger.info(
                    "[Receiver] task_done_event set: role=%s task_id=%s rev=%s",
                    _role, _tid, _rev,
                )

    async def run(self) -> None:
        """Endlosschleife: scan -> publish -> sleep. Wird via task.cancel() beendet."""
        self.running = True
        logger.info("[Receiver] Loop started (interval=%.1fs)", self.interval)
        try:
            while self.running:
                try:
                    items = self.scan_once()
                    for it in items:
                        await self.transport.publish_response(
                            role=it["role"], payload=it["payload"], correlation_id=it["correlation_id"]
                        )
                        # Notify spawn loop that this task's response has been published.
                        self._signal_task_done(it.get("payload") or {})
                except Exception as e:
                    logger.exception(f"[Receiver] scan error: {e}")
                await asyncio.sleep(self.interval)
        finally:
            self.running = False
            logger.info("[Receiver] Loop stopped.")


# _materialize_to_workspace is imported above from engine.services.workspace_materializer
# (shared service, identical semantics for PiMesh Receiver and in-process path).


def make_pimesh_messenger_callback(transport, provider, crew_cwds, project_root, models):
    '''Erzeugt die messenger_callback (single authority) fuer PiMesh-Modus.

    (a) transport.dispatch() schreibt task-N.json(+md); (b) PiProvider.spawn_for_assignment()
    spawned pi im Crew-Dir (fire-and-forget). defense-in-depth: pro (task_id, state_revision)
    hoechstens ein Spawn.

    REVIEWER-Dummy-Bypass (Wiring-Ebene, KEIN Kernel-Change):
    Ein deterministischer Reviewer, der per Definition immer APPROVE sagt, ist semantisch
    identisch zum Verifier im Kernel -> ein deterministischer Check (immer wahr), KEIN
    probabilistischer LLM-Call. Wir publishen REVIEW_APPROVED direkt in die Transport-Queue,
    sparen LLM-Spawn + WORKER_TIMEOUT. Der Kernel/Guardian verarbeitet es wie immer.
    '''
    spawned = set()
    spawn_sem = asyncio.Semaphore(MAX_CONCURRENT_SPAWNS)
    active_spawns = {}
    task_done_events: Dict[tuple, asyncio.Event] = {}
    task_assigned_at: Dict[str, Tuple[str, float]] = {}

    async def _spawn_limited(role, payload, crew_cwd, model, session_id, session_dir, correction_note, spawn_key, task_assigned_at):
        task_id = payload.get('task_id')
        if task_id:
            task_assigned_at[task_id] = (role, time.time())
        # Begrenzt die ANZAHL gleichzeitig laufender `pi`-Subprozesse. Slot wird bis
        # Outcome (Response published / Timeout / Proc-Exit) gehalten -> vermeidet
        # Free-Tier Rate-Limits / 320s-Timeouts durch 3+ gleichzeitige Calls.
        async with spawn_sem:
            proc = provider.spawn_for_assignment(
                role=role,
                task_id=payload['task_id'],
                run_id=payload['run_id'],
                state_revision=payload['state_revision'],
                crew_cwd=crew_cwd,
                model=model,
                session_id=session_id,
                session_dir=session_dir,
                correction_note=correction_note,
                tools=PiProvider.tools_for_role(role),
            )
            logger.info(
                '[pimesh] spawned %s worker for %s (model=%s, session_mode=%s, session_id=%s) '
                '[active_spawns=%d/%d]',
                role, payload['task_id'], model, SESSION_MODE, session_id,
                MAX_CONCURRENT_SPAWNS - spawn_sem._value, MAX_CONCURRENT_SPAWNS,
            )
            if proc is None:
                return
            active_spawns[spawn_key] = proc
            done_event = asyncio.Event()
            task_done_events[spawn_key] = done_event
            try:
                # Wait for EITHER proc exit OR task done (receiver published response).
                # Timeout fallback: worst case proc.wait() returns eventually.
                proc_fut = asyncio.get_event_loop().run_in_executor(None, proc.wait)
                event_fut = asyncio.create_task(done_event.wait())
                try:
                    done, pending = await asyncio.wait(
                        [proc_fut, event_fut],
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                except asyncio.CancelledError:
                    # _spawn_limited itself was cancelled (e.g., run shutdown).
                    for p in (proc_fut, event_fut):
                        if not p.done():
                            p.cancel()
                    raise
                finally:
                    _pending = locals().get("pending", [])
                    for p in _pending:
                        if not p.done():
                            p.cancel()
                    # Ensure futures are consumed to avoid "Task exception was never retrieved".
                    for p in locals().get("done", []):
                        try:
                            p.result()
                        except Exception:
                            pass
            finally:
                active_spawns.pop(spawn_key, None)
                task_done_events.pop(spawn_key, None)

    async def wrapper(payload):
        key = (payload.get('task_id'), payload.get('state_revision'))
        if key in spawned:
            logger.warning('[pimesh] skip duplicate spawn %s', key)
            return
        spawned.add(key)

        role = payload.get('role')

        # ---- REVIEWER DUMMY BYPASS (kein LLM, kein Spawn) ----
        if role == 'REVIEWER' and REVIEWER_IS_DUMMY:
            tid = payload.get('task_id')
            td = payload.get('task_definition') or {}
            is_retry = bool(td.get('previous_feedback'))
            if REVIEWER_DUMMY_REJECT_ONCE and not is_retry:
                logger.info('[pimesh] Dummy-Reviewer REJECT-ONCE for %s (diagnostic, first review)', tid)
                dummy_response = {
                    'protocol_version': '1.0',
                    'message_id': f"mock-{tid}",
                    'run_id': payload.get('run_id'),
                    'task_id': tid,
                    'state_revision': payload.get('state_revision'),
                    'event': 'REVIEW_FAILURE',
                    'sender_role': 'REVIEWER',
                    'artifacts': [],
                    'plan_draft': None,
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'logs': 'Diagnostic REVIEW_FAILURE (FIRMA_REVIEWER_DUMMY_REJECT_ONCE): '
                            'verify acceptance criteria are met EXACTLY (e.g., required API/markup).',
                }
                await transport.publish_response(
                    role='REVIEWER', payload=dummy_response, correlation_id=tid,
                )
                return
            logger.info('[pimesh] Dummy-Reviewer bypass for %s (no LLM spawn)', tid)
            dummy_response = {
                'protocol_version': '1.0',
                'message_id': f"mock-{payload.get('task_id')}-{uuid.uuid4().hex[:8]}",
                'run_id': payload.get('run_id'),
                'task_id': payload.get('task_id'),
                'state_revision': payload.get('state_revision'),
                'event': 'REVIEW_APPROVED',
                'sender_role': 'REVIEWER',
                'artifacts': [],
                'plan_draft': None,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'logs': 'Auto-approved by deterministic dummy bypass (no LLM).',
            }
            await transport.publish_response(
                role='REVIEWER', payload=dummy_response, correlation_id=payload.get('task_id'),
            )
            return

        # ---- NORMAL FLOW: PLANNER & CODER (& REVIEWER real) ----
        review_artifacts = None
        if role == 'REVIEWER':
            review_artifacts = _load_artifacts_for_review(payload.get('run_id'), payload.get('task_id'), payload)
        crew_rel = crew_cwds.get(role)
        if not crew_rel:
            logger.error('[pimesh] no crew dir for role %s; dispatch only', role)
            await transport.dispatch(payload, review_artifacts=review_artifacts)
            return
        crew_cwd = os.path.join(project_root, crew_rel)

        # ---- Phase 6.2 Fix 1: CODER-RETRY-SCRUB ----
        # Verhindert, dass der Retry-Coder seine eigene "Ich bin fertig"-Session
        # (Session-Kontinuitaet) sieht und den Retry verweigert (task-2 Loop).
        correction_note = None
        if role == 'CODER':
            td = payload.get('task_definition') or {}
            if td.get('previous_feedback'):
                _scrub_retry_response(crew_cwd, payload['task_id'])
                correction_note = (
                    "OVERRIDE: Dein VORHERIGER Versuch fuer diese Task wurde vom REVIEWER "
                    "ABGELEHNT (nicht vom User wiederholt). Die Aufgabe ist NICHT abgeschlossen. "
                    "Lies das 'Previous feedback'-Segment in der Spec, behebe es gezielt, und "
                    "schreibe eine FRISCHE worker_response-Datei mit dem im Assignment angegebenen "
                    "state_revision. Beende NICHT mit der Behauptung, die Aufgabe sei schon erledigt."
                )

        await transport.dispatch(payload, review_artifacts=review_artifacts)
        # DEBUG: list visible tasks in crew_cwd before spawn
        _tasks_dir = os.path.join(crew_cwd, '.pi', 'messenger', 'crew', 'tasks')
        _visible_tasks = []
        if os.path.isdir(_tasks_dir):
            _visible_tasks = sorted(os.listdir(_tasks_dir))
        logger.info(
            '[PiMesh-Debug] pre-spawn task listing: role=%s task_id=%s visible_tasks=%s',
            role, payload.get('task_id'), _visible_tasks,
        )
        model = models.get(role)
        session_id = None
        session_dir = None
        # Phase 6.3 Step 1: Session unabhaengig von FIRMA_MODE. Gate ueber SESSION_MODE.
        # Default SESSION_MODE=off == heute (deterministic, --no-session). FIRMA_MODE
        # (collaborative) schaltet Sessions NICHT mehr automatisch an -- wer Sessions
        # will, setzt FIRMA_SESSION_MODE=task|persona_base explizit.
        if SESSION_MODE != "off":
            if SESSION_MODE == "persona_base":
                # 6.3.a: Warm-Base copy-on-start. Department aus Rolle, Persona aus Config.
                department = SessionRegistry.ROLE_DEPARTMENT.get(role, "coding")
                base_dir = SessionRegistry.base_session_dir_for(department, PERSONA_ID, role)
                task_dir = SessionRegistry.session_dir_for(payload['run_id'])
                target_id = SessionRegistry.session_id_for(payload['run_id'], payload['task_id'], role)
                cap = MAX_SESSION_DISK_MB_PER_RUN
                seeded = SessionRegistry.copy_base_to_task(base_dir, task_dir, target_id, cap_mb=cap)
                if not seeded and cap and SessionRegistry._dir_size_mb(base_dir) > cap:
                    logger.warning(
                        "[pimesh] persona_base base exceeds cap (%s MB) for run %s -> "
                        "spawn WITHOUT session (fail-safe)", cap, payload['run_id']
                    )
                    session_id = None
                    session_dir = None
                else:
                    session_id = target_id
                    session_dir = str(task_dir)
                # Observability (Explizit: department/persona_id/base_dir/task_session_dir)
                logger.info(
                    "[pimesh] persona_base spawn run=%s role=%s department=%s persona_id=%s "
                    "base_dir=%s task_session_dir=%s session_id=%s seeded=%s",
                    payload['run_id'], role, department, PERSONA_ID, base_dir, task_dir,
                    session_id, seeded,
                )
                if not seeded and not (cap and SessionRegistry._dir_size_mb(base_dir) > cap):
                    logger.info(
                        "[pimesh] persona_base: no base at %s -> task-mode (no warm context)", base_dir
                    )
            else:  # "task"
                # Stufe 2 Disk-Guard: Cap pro Run. Bei Ueberschreitung fail-safe OHNE
                # Session spawnen (kein Crash, keine unkontrollierte Disk-Growth).
                cap = MAX_SESSION_DISK_MB_PER_RUN
                if cap and SessionRegistry.session_dir_size_mb(payload['run_id']) > cap:
                    logger.warning(
                        "[pimesh] Session disk cap (%s MB) exceeded for run %s -> "
                        "spawn WITHOUT session (fail-safe)", cap, payload['run_id']
                    )
                else:
                    session_id = SessionRegistry.session_id_for(payload['run_id'], payload['task_id'], role)
                    session_dir = str(SessionRegistry.session_dir_for(payload['run_id']))
        spawn_key = (payload.get('task_id'), payload.get('state_revision'), role)
        asyncio.create_task(
            _spawn_limited(role, payload, crew_cwd, model, session_id, session_dir, correction_note, spawn_key, task_assigned_at)
        )

    return wrapper, spawned, task_done_events, task_assigned_at


# ---------------------------------------------------------------------------
# Kernel Bootstrap (gespiegelt von run_snake.main_logic, aber pimesh)
# ---------------------------------------------------------------------------
async def main_logic():
    from engine.controller import RunController
    from engine.services.run_archive import RunArchiver
    from engine.scheduler import Scheduler
    from engine.services.execution import ExecutionService
    from engine.services.sandbox import LocalPythonSandbox
    from engine.db import DatabaseManager
    from engine.models import Base

    VerificationRegistry = _verification_registry()
    VerificationRegistry.register("structural_web", _web_verifier())

    db_path = DB_DIR / "snake_pimesh.db"
    if db_path.exists():
        import time
        for attempt in range(5):
            try:
                os.remove(db_path)
                break
            except PermissionError:
                if attempt < 4:
                    time.sleep(0.5)
                else:
                    raise
    db_manager = DatabaseManager(f"sqlite+aiosqlite:///{db_path}")
    async with db_manager.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    def scheduler_factory(db, messenger_callback):
        return Scheduler(db, messenger_callback=messenger_callback)

    def transport_factory():
        return PiMeshTransport(crew_cwds=PIMESH_CREWS, project_root=str(BASE_DIR))

    execution_service = ExecutionService(db_manager)
    sandbox = LocalPythonSandbox()

    controller = RunController(
        db_manager=db_manager,
        scheduler_factory=scheduler_factory,
        transport_factory=transport_factory,
        execution_service=execution_service,
        sandbox=sandbox,
    )

    config = _snake_config()
    logger.info("🚀 Starting PiMesh Snake Run...")
    run_id = await controller.create_run(config)

    run_archiver = RunArchiver()
    run_archiver.attach_run_log_handler(run_id)

    shared_transport = transport_factory()
    controller.transport_factory = lambda: shared_transport

    # PiMesh: echte Worker ueber pi spawnen (single authority: Scheduler CLAIM
    # -> dispatch + PiProvider-Spawn). Ohne messenger_callback wuerde nur dispatchen,
    # aber KEINE pi-Worker starten -> PLANNER-TIMEOUT.
    provider = PiProvider()
    pimesh_callback, _spawned, task_done_events, task_assigned_at = make_pimesh_messenger_callback(
        transport=shared_transport,
        provider=provider,
        crew_cwds=PIMESH_CREWS,
        project_root=str(BASE_DIR),
        models=PIMESH_MODELS,
    )
    await controller.start_run(run_id, messenger_callback=pimesh_callback)
    receiver = PiMeshReceiverLoop(
        transport=shared_transport,
        crew_cwds=PIMESH_CREWS,
        project_root=str(BASE_DIR),
        expected_run_id=run_id,
        task_done_events=task_done_events,
        task_assigned_at=task_assigned_at,
    )
    if DEBUG_RECEIVER_RECOVERY:
        for role, cwd in PIMESH_CREWS.items():
            worker_dir = receiver._worker_dir(cwd)
            logger.info(
                '[Receiver-Path] role=%s crew_cwd=%s worker_dir=%s run_id=%s',
                role, cwd, worker_dir, run_id,
            )
    receiver_task = asyncio.create_task(receiver.run())

    try:
        last_status = None
        while True:
            status_info = await controller.get_run_status(run_id)
            status = status_info["status"]
            if status != last_status:
                logger.info(f"🌟 [RUN STATUS UPDATE] {status} | Metrics: {status_info['metrics']}")
                last_status = status
            if status in ["COMPLETED", "FAILED", "CANCELLED"]:
                logger.info(f"🏁 Run reached terminal state: {status}")
                try:
                    await run_archiver.archive_run(run_id, controller, config)
                except Exception as exc:
                    logger.warning(f"[Archiver] archiving failed (non-fatal): {exc}")
                run_archiver.detach_run_log_handler(run_id)
                break
            await asyncio.sleep(5)
    finally:
        receiver.running = False
        receiver_task.cancel()
        await controller.stop_run(run_id)
        logger.info("✅ PiMesh Snake Run finished.")


# ---------------------------------------------------------------------------
# lokale Helfer (vermeidet schwere Top-Level-Imports im Baselinemodul)
# ---------------------------------------------------------------------------
def _review_target_paths(payload: Dict[str, Any]) -> List[str]:
    td = payload.get("task_definition") or {}
    exp = td.get("expected_artifacts") or payload.get("expected_artifacts") or []
    paths: List[str] = []
    for e in exp:
        if isinstance(e, str):
            paths.append(e)
        elif isinstance(e, dict):
            p = e.get("path")
            if isinstance(p, str):
                paths.append(p)
    if not paths:
        coder_arts = payload.get("review_artifacts_meta") or payload.get("artifacts") or []
        for a in coder_arts:
            if isinstance(a, dict):
                p = a.get("path")
                if isinstance(p, str):
                    paths.append(p)
    normalized = []
    for p in paths:
        p = p.strip().lstrip("/").replace("\\", "/")
        if not p or ".." in p.split("/"):
            continue
        normalized.append(p)
    return sorted(set(normalized))


def _load_artifacts_for_review(run_id: str, task_id: str, payload: Dict[str, Any]) -> Dict[str, str]:
    """Liest nur die für diesen Reviewer-Task relevanten Artefakte.

    Relevanz:
    1. `payload["task_definition"]["expected_artifacts"]` (string oder dict mit path)
    2. Fallback: tatsächlich vorhandene Dateien unter `ARTIFACT_DIR/<run_id>/<task_id>/`

    Security: keine Path Traversal, keine absoluten Pfade.
    """
    import pathlib

    target_paths = _review_target_paths(payload)
    base = pathlib.Path(ARTIFACT_DIR) / (run_id or "") / (task_id or "")

    def _safe_path(name: str) -> Optional[str]:
        name = name.strip().lstrip("/").replace("\\", "/")
        if not name or ".." in name.split("/"):
            return None
        return name

    # Strategy 1: use explicit expected_artifacts if available
    if target_paths:
        out: Dict[str, str] = {}
        for rel_path in target_paths:
            safe = _safe_path(rel_path)
            if safe is None:
                continue
            abs_path = base / safe
            try:
                if abs_path.is_file():
                    out[safe] = abs_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass
        return out

    # Strategy 2: fallback to actual files present in the artifact directory
    out = {}
    if base.is_dir():
        for p in sorted(base.iterdir()):
            if p.is_file():
                safe = _safe_path(p.name)
                if safe is None:
                    continue
                try:
                    out[safe] = p.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    pass
    return out


def _verification_registry():
    from engine.services.verification_registry import VerificationRegistry
    return VerificationRegistry


def _web_verifier():
    from engine.services.verifiers.web_verifier import WebStructuralVerifier
    return WebStructuralVerifier


def _snake_config() -> Dict[str, Any]:
    prompt = (
        "Erstelle eine professionelle, moderne Website für das Open-Source-Projekt \"Firma\".\n\n"
        "Firma ist ein deterministisches Multi-Agenten-Execution-Framework für Softwareprojekte. "
        "Es orchestriert autonome KI-Worker (Researcher, Planner, Coder, Reviewer) über ein strukturiertes Task-System "
        "mit strengen Zustandsmaschinen, zustandslosen Workern, Artefakt-Pipelines und reproduzierbaren Runs.\n\n"
        "Die Website soll den Eindruck eines durchdachten, technisch anspruchsvollen Open-Source-Projekts vermitteln, "
        "nicht den einer Hobby-Bastelbude. Sie soll schick, vertrauenswürdig und informativ sein und einen klaren roten Faden haben.\n\n"
        "Bitte liefere eine vollständige, produktionsreife Website mit mindestens folgenden Inhalten:\n"
        "- Hero-Bereich mit klarer Projektpositionierung\n"
        "- Architektur/Workflow-Uebersicht (Researcher, Planner, Coder, Reviewer, Guardian, Orchestrator)\n"
        "- Features/Staerken (Determinismus, Reproduzierbarkeit, Read-only-Worker, Artefakt-Tracking, Auditing)\n"
        "- Einsatzzweck/Nutzen\n"
        "- Projektstatus/Reife (Meilensteine, lauffaehige Pipeline)\n"
        "- Installations-/Startabschnitt\n"
        "- Vertrauenselemente (Governance, nachvollziehbare Runs)\n\n"
        "Gestalterisch soll die Seite professionell und modern wirken: klare visuelle Hierarchie, gute Typografie, "
        "ruhige Tiefe, kein ueberladener Slider-Kram. Sie soll auf Mobilgeraeten und Desktop gleichermassen funktionieren.\n\n"
        "Technische Rahmenbedingungen:\n"
        "- Plain HTML/CSS/JS, keine Build-Tools, keine externen Frameworks\n"
        "- Es muessen genau diese Dateien entstehen: index.html, style.css, app.js\n"
        "- Die Seite muss durch Oeffnen von index.html im Browser funktionsfaehig bleiben\n"
        "- Barrierefreiheit und Ladezeit beachten\n\n"
        "Return ONLY the JSON object."
    )
    extra = os.environ.get("FIRMA_PLANNER_EXTRA_INSTRUCTION")
    if extra:
        prompt += "\n\n" + extra
    return {
        "project_name": "Firma Project Website (PiMesh)",
        "plan_name": "Professional Firma Website",
        "prompt": prompt,
        "expected_artifacts": ["index.html", "style.css", "app.js"],
        "acceptance_criteria": [
            "EXISTS:index.html",
            "EXISTS:style.css",
            "EXISTS:app.js",
            "CONTAINS:index.html:Firma",
            "CONTAINS:index.html:Architektur",
            "CONTAINS:style.css:root",
            "CONTAINS:app.js:addEventListener",
        ],
        "verification_type": "structural_web",
    }


async def main():
    try:
        await asyncio.wait_for(main_logic(), timeout=1200)
    except asyncio.TimeoutError:
        logger.error("❌ Run timed out after 1200 seconds.")
    except Exception as e:
        logger.exception(f"Critical error during run: {e}")


if __name__ == "__main__":
    asyncio.run(main())
