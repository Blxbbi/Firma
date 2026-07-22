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
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from engine.settings import (
    BASE_DIR, DB_DIR, ARTIFACT_DIR, FIRMA_TRANSPORT, PIMESH_CREWS, REVIEWER_IS_DUMMY,
    FIRMA_MODE, SESSION_DIR, REVIEWER_DUMMY_REJECT_ONCE,
)
from engine.transport.pi_mesh_transport import PiMeshTransport, WORKER_RESPONSE_SUFFIX
from engine.models import WorkerResponse, TaskEvent, AssignedRole
from engine.session_registry import SessionRegistry

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("run_pi_mesh")


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
    ):
        self.transport = transport
        self.crew_cwds = crew_cwds
        self.project_root = project_root
        self.interval = interval
        self._consumed: set = set()
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
                                art["content"] = f.read()
                        except Exception as e:
                            logger.warning(f"[Receiver] Cannot read {fp}: {e}")
                            art["content"] = None
                    else:
                        art["content"] = None
            elif action == "DELETE":
                art["content"] = None
        return worker_payload, unsafe

    def _response_artifacts_pending(self, crew_cwd, wp) -> bool:
        """True wenn ein CREATE/UPDATE-Artefakt noch nicht auf Disk liegt.

        Das Modell schreibt die worker_response-Datei oft mehrfach um (je nach Datei,
        die es gerade erzeugt hat). Solange ein referenziertes Artefakt fehlt, wird der
        Scan deferiert, um Race-Conditions + falsche Artifact-Contract-Violations zu meiden.
        """
        if not isinstance(wp, dict):
            return False
        arts = wp.get("artifacts") or []
        worker_dir = self._worker_dir(crew_cwd)
        for art in arts:
            if not isinstance(art, dict):
                continue
            if art.get("action") in ("CREATE", "UPDATE"):
                p = self._safe_path(worker_dir, art.get("path", ""))
                if p is None:
                    # Unsicherer Pfad (absolute/'..') -> vom _inline_content als
                    # Security-Boundary behandelt, NICHT deferen (sonst Endlosschleife).
                    continue
                if not os.path.isfile(p):
                    return True
        return False

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
                state_revision = wp.get("state_revision") if isinstance(wp, dict) else None
                key = (task_id, state_revision)
                if key in self._consumed:
                    continue

                # Defer: referenzierte Artefakt-Dateien noch nicht auf Disk?
                # (Worker schreibt die Response-Datei mehrfach um -> Race vermeiden)
                if self._response_artifacts_pending(crew_cwd, wp):
                    logger.debug(f"[Receiver] Defer {task_id} (rev {state_revision}): artifacts not on disk yet")
                    continue

                worker_payload = wp
                worker_payload, unsafe = self._inline_content(crew_cwd, worker_payload)

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
        return out

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
                except Exception as e:
                    logger.exception(f"[Receiver] scan error: {e}")
                await asyncio.sleep(self.interval)
        finally:
            self.running = False
            logger.info("[Receiver] Loop stopped.")


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
                    'message_id': f"mock-{tid}-{uuid.uuid4().hex[:8]}",
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
            review_artifacts = _load_artifacts_for_review(payload.get('run_id'), payload.get('task_id'))
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
        model = models.get(role)
        session_id = None
        session_dir = None
        if SessionRegistry.is_collaborative():
            session_id = SessionRegistry.session_id_for(payload['run_id'], payload['task_id'], role)
            session_dir = str(SessionRegistry.session_dir_for(payload['run_id']))
        provider.spawn_for_assignment(
            role=role,
            task_id=payload['task_id'],
            run_id=payload['run_id'],
            state_revision=payload['state_revision'],
            crew_cwd=crew_cwd,
            model=model,
            session_id=session_id,
            session_dir=session_dir,
            correction_note=correction_note,
        )
        logger.info('[pimesh] spawned %s worker for %s (model=%s)', role, payload['task_id'], model)

    return wrapper, spawned


# ---------------------------------------------------------------------------
# Kernel Bootstrap (gespiegelt von run_snake.main_logic, aber pimesh)
# ---------------------------------------------------------------------------
async def main_logic():
    from engine.controller import RunController
    from engine.services.run_archive import RunArchiver
    from engine.scheduler import Scheduler
    from engine.services.execution import ExecutionService
    from engine.services.sandbox import LocalPythonSandbox
    from engine.repository import DatabaseManager
    from engine.models import Base

    VerificationRegistry = _verification_registry()
    VerificationRegistry.register("structural_web", _web_verifier())

    db_path = DB_DIR / "snake_pimesh.db"
    if db_path.exists():
        os.remove(db_path)
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

    await controller.start_run(run_id)
    receiver = PiMeshReceiverLoop(transport=shared_transport, crew_cwds=PIMESH_CREWS, project_root=str(BASE_DIR))
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
def _load_artifacts_for_review(run_id, task_id):
    """Liest die vom CODER persistierten Artefakte, damit der Reviewer sie reviewen kann."""
    import pathlib
    base = pathlib.Path(ARTIFACT_DIR) / (run_id or "") / (task_id or "")
    out = {}
    if base.is_dir():
        for p in sorted(base.iterdir()):
            if p.is_file():
                try:
                    out[p.name] = p.read_text(encoding="utf-8", errors="replace")
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
    return {
        "project_name": "Retro Snake Game (PiMesh)",
        "plan_name": "Classic Snake Implementation",
        "prompt": (
            "You are an expert web developer. Create a fully functional, retro-style Snake game as a web app.\n\n"
            "CRITICAL DELIVERY REQUIREMENTS:\n"
            "1. You MUST produce exactly these three files:\n"
            "   - index.html (The main page containing the game canvas)\n"
            "   - style.css (Retro arcade aesthetics: dark background, neon colors, pixel font)\n"
            "   - game.js (Complete game logic: movement, food growth, collision detection, scoring)\n"
            "2. No Python files. No requirements.txt. No explanations. No markdown text outside the JSON.\n"
            "3. The game must be immediately playable in a browser.\n"
            "4. Use HTML5 Canvas for the game board.\n"
            "5. Implement classic snake mechanics: arrow keys for movement, eating food to grow, game over on wall/self collision.\n\n"
            "Return ONLY the JSON object."
        ),
        "expected_artifacts": ["index.html", "style.css", "game.js"],
        "acceptance_criteria": [
            "EXISTS:index.html",
            "EXISTS:style.css",
            "EXISTS:game.js",
            "CONTAINS:index.html:<canvas",
            "CONTAINS:game.js:requestAnimationFrame",
            "CONTAINS:game.js:addEventListener('keydown'",
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
