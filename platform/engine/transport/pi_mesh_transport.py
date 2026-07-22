"""
PiMeshTransport — file-based Bridge-Implementierung von WorkerTransport.

Design-Entscheidungen (siehe docs/PiMesh_Architektur.md §9, §10, §13):
- Firma-Python ruft pi-messenger NICHT ueber ein Tool/CLI auf.
- dispatch() materialisiert Assignments als pi-messenger Task-Dateien auf Disk
  (<crew-cwd>/.pi/messenger/crew/tasks/task-N.json + task-N.md).
- Die Crew-WORKER (LLM-Agenten) werden durch Firma selbst gestartet: PiProvider
  spawned pro Assignment einen `pi --mode json` Subprozess im jeweiligen Crew-cwd
  (cwd = Crew-Dir, kein pi_messenger-Tool-Aufruf, kein cwd-Problem).
- poll()/publish_response() bleiben identisch zu InternalTransport: interne Queue,
  damit der Orchestrator blind weiterhin poll() + Flattening nutzen kann.

Verifiziertes pi-messenger Task-Schema (crew/types.ts, crew/store.ts):
  Task = { id: "task-N", title, status: "todo"|"in_progress"|"done"|"blocked",
           depends_on: [], created_at, updated_at, attempt_count, ... }
  Pfad: <crew-cwd>/.pi/messenger/crew/tasks/<id>.json  +  <id>.md (Spec)
"""
import asyncio
import json
import os
import tempfile
import shutil
import datetime
from typing import Any, Dict, List, Optional

from engine.transport.base import WorkerTransport, TransportMessage

import logging
logger = logging.getLogger(__name__)

WORKER_RESPONSE_SUFFIX = ".response.json"  # contract: worker_response.<task_id>.response.json


class PiTaskFile:
    """Minimaler, von Firma geschriebener Ausschnitt des pi-messenger Task-Schemas.

    Nur die Felder, die pi-messenger's `work` zum Erkennen eines 'ready' Tasks
    braucht. `firma_assignment` ist ein Custom-Feld (von pi-messenger ignoriert,
    nuetzlich fuer Debug/Receiver).
    """

    def __init__(
        self,
        id: str,
        title: str,
        status: str = "todo",
        depends_on: Optional[List[str]] = None,
        created_at: str = "",
        updated_at: str = "",
        attempt_count: int = 0,
        firma_assignment: Optional[Dict[str, Any]] = None,
    ):
        self.id = id
        self.title = title
        self.status = status
        self.depends_on = depends_on or []
        self.created_at = created_at
        self.updated_at = updated_at
        self.attempt_count = attempt_count
        self.firma_assignment = firma_assignment

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "depends_on": self.depends_on,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "attempt_count": self.attempt_count,
        }
        if self.firma_assignment is not None:
            d["firma_assignment"] = self.firma_assignment
        return d


class PiMeshTransport(WorkerTransport):
    """File-based Bridge: Engine -> pi-messenger Task-Files, Worker -> interne Queue."""

    PROTOCOL_VERSION = "1.0"
    ROLE_TO_CREW = {"PLANNER": "planning-crew", "CODER": "coding-crew", "REVIEWER": "reviewing-crew"}
    ROLE_TARGET_EVENT = {
        "PLANNER": "PLAN_SUBMITTED",
        "CODER": "CODE_SUBMITTED",
        "REVIEWER": "REVIEW_APPROVED",
    }

    def __init__(self, crew_cwds: Dict[str, str], project_root: str):
        """
        crew_cwds: Mapping role -> crew directory NAME (relativ zu project_root),
                   z.B. {"PLANNER": "pimesh/planning-crew", ...}
        project_root: Firma-Projekt-Root (absolut), in dem die Crew-Dirs liegen.
        """
        self._queue: "asyncio.Queue[TransportMessage]" = asyncio.Queue()
        self.crew_cwds = crew_cwds
        self.project_root = project_root

    # ------------------------------------------------------------------ helpers
    def _crew_cwd(self, role: str) -> str:
        name = self.ROLE_TO_CREW.get(role)
        if not name:
            raise ValueError(f"[PiMeshTransport] Unknown role routing: {role}")
        return os.path.join(self.project_root, self.crew_cwds.get(role, name))

    def _tasks_dir(self, crew_cwd: str) -> str:
        return os.path.join(crew_cwd, ".pi", "messenger", "crew", "tasks")

    @staticmethod
    def _atomic_write(path: str, data: str) -> None:
        """Temp + rename (atomar, vermeidet halbe Dateien fuer den Receiver)."""
        d = os.path.dirname(path)
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(data)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    def _worker_response_filename(self, task_id: str) -> str:
        return f"worker_response.{task_id}{WORKER_RESPONSE_SUFFIX}"

    def _build_spec_markdown(self, payload: Dict[str, Any], review_artifacts: Optional[Dict[str, str]] = None) -> str:
        """Die Spec, die der Crew-Worker als Task-Beschreibung liest.

        Enthaelt das vollstaendige Firma TASK_ASSIGNMENT (run_id, task_id,
        state_revision, prompt, task_definition) + den exakten, rolle-spezifischen
        Worker-Vertrag (Dateiname, enums, pfad-regeln, reihenfolge).
        """
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        task_id = payload.get("task_id")
        run_id = payload.get("run_id")
        role = payload.get("role")
        state_revision = payload.get("state_revision")
        target_event = self.ROLE_TARGET_EVENT.get(role, "CODE_SUBMITTED")
        assignment = {
            "run_id": run_id,
            "task_id": task_id,
            "state_revision": state_revision,
            "prompt": payload.get("prompt"),
            "task_definition": payload.get("task_definition"),
        }
        resp_file = self._worker_response_filename(task_id)
        td = payload.get("task_definition") or {}
        criteria = td.get("acceptance_criteria") or []
        expected = td.get("expected_artifacts") or []
        example_path = "<your_file>"
        if expected and isinstance(expected[0], dict) and expected[0].get("path"):
            example_path = expected[0]["path"]

        parts: list = []
        parts.append(f"# Firma Task {task_id}  (Role: {role})\n\n")
        parts.append(
            "Du bist ein pi-messenger Crew-Worker im Auftrag der Firma-Execution-Engine.\n"
            "Die Firma Engine ist der ALLEINIGE State-Owner. Du bist ein zustandsloser Worker:\n"
            "du liest nur dieses Assignment, schreibst Artefakte + eine Response-Datei, und kehrst zurueck.\n\n"
        )
        parts.append("## Assignment (TASK_ASSIGNMENT)\n\n")
        parts.append(f"```json\n{json.dumps(assignment, indent=2, ensure_ascii=False)}\n```\n\n")

        if role == "PLANNER":
            parts.append(
                "## Deine Aufgabe (AUTHORITATIVE)\n"
                "Du erstellst EINEN Plan (`plan_draft`). Schreibe KEINEN Code.\n\n"
            )
        elif role == "REVIEWER":
            parts.append("## Global Goal (BACKGROUND ONLY)\n")
            parts.append(
                "Der `prompt` im Assignment beschreibt das GESAMT-Projekt (Hintergrundkontext).\n\n"
            )
            parts.append("## Your Task (AUTHORITATIVE)\n")
            parts.append(
                "Du bist REVIEWER. Du implementierst NICHTS. Du PRUEFST die unten stehende "
                "CODER-Implementierung gegen die Task-Beschreibung und die Acceptance Criteria. "
                "Entscheide: ist der Code korrekt, vollstaendig und ohne offensichtliche Bugs? "
                "Emittiere `REVIEW_APPROVED` (gut) oder `REVIEW_FAILURE` (mit konkretem Grund).\n\n"
            )
            if criteria:
                parts.append("### Acceptance Criteria (MUST PASS) — das wurde vom CODER gefordert:\n")
                for c in criteria:
                    parts.append(f"- `{c}`\n")
                parts.append("\n")
            parts.append("## Code to Review (vom CODER produziert)\n")
            if review_artifacts:
                for fname, content in review_artifacts.items():
                    parts.append(f"### Datei: `{fname}`\n")
                    parts.append(f"```\n{content}\n```\n\n")
            else:
                parts.append("_(keine Artefakte gefunden — pruefe, ob der CODER welche geliefert hat)_\n\n")
        else:  # CODER
            parts.append("## Global Goal (BACKGROUND ONLY)\n")
            parts.append(
                "Der `prompt` im Assignment beschreibt das GESAMT-Projekt. Interpretiere ihn NICHT "
                "als deine Aufgabenliste — er dient NUR als Hintergrundkontext.\n\n"
            )
            desc = td.get("description") or "(siehe task_definition)"
            parts.append("## Your Task (AUTHORITATIVE)\n")
            parts.append(f"Du implementierst ausschliesslich: **{desc}**\n")
            parts.append(
                "Du darfst NUR die in `task_definition` genannten Dateien anfassen "
                "(keine weiteren Dateien schreiben).\n\n"
            )
            if criteria:
                parts.append("### WICHTIG: Verifier / Kernel Acceptance Criteria (MUST PASS)\n")
                parts.append("Diese Kriterien werden HART geprueft. Implementiere sie WORTWORTLICH.\n")
                for c in criteria:
                    parts.append(f"- `{c}`\n")
                parts.append(
                    "Beispiel: falls `innerHTML` gefordert ist, nutze `innerHTML`, NICHT `textContent`.\n\n"
                )
                feedback = td.get("previous_feedback")
                if feedback:
                    parts.append("## ⚠️ PREVIOUS ATTEMPT WAS REJECTED BY THE REVIEWER\n")
                    parts.append(
                        "Dein vorheriger Versuch fuer diese Task wurde vom REVIEWER ABGELEHNT — "
                        "die Aufgabe ist NICHT abgeschlossen. Die folgende Kritik MUSST du beheben. "
                        "Behalte den uebrigen Ansatz bei, schreibe die Dateien NEU (nicht nur "
                        "behaupten, sie seien fertig), und erzeuge anschliessend eine FRISCHE "
                        "worker_response-Datei mit dem im Assignment angegebenen state_revision:\n\n"
                    )
                    parts.append(f"> {feedback}\n\n")

        parts.append("## Output Contract (MUSS exakt eingehalten werden)\n")
        parts.append(
            f"Schreibe ANSCHLIESSEND eine Datei namens **`{resp_file}`** in das Verzeichnis "
            "`.pi/messenger/crew/`** (dasselbe Verzeichnis, das den `tasks/`-Unterordner enthaelt; "
            "NICHT im tasks/-Ordner), mit DIESEM Schema:\n"
        )
        parts.append("```json\n")
        parts.append('{\n')
        parts.append('  "protocol_version": "1.0",\n')
        parts.append('  "message_id": "<eindeutige uuid>",\n')
        parts.append("  # WICHTIG: message_id MUSS ECHT eindeutig sein (z.B. task-3-a1b2c3d4), KEINE Platzhalter kopieren!\n")
        parts.append(f'  "task_id": "{task_id}",\n')
        parts.append(f'  "run_id": "{run_id}",\n')
        parts.append(f'  "state_revision": {state_revision},\n')
        parts.append(f'  "event": "{target_event}",\n')
        parts.append(f'  "sender_role": "{role}",\n')
        parts.append(f'  "artifacts": [{{"path": "{example_path}", "action": "CREATE", "content": null}}],\n')
        parts.append(f'  "timestamp": "{now}",\n')
        parts.append('  "logs": "<freier Status-Text>"\n')
        parts.append("}\n```\n\n")

        parts.append("### Erlaubte Enums\n")
        parts.append(
            "- event: PLAN_SUBMITTED | CODE_SUBMITTED | REVIEW_APPROVED | REVIEW_FAILURE | TASK_FAILED\n"
            f"  - Deine Rolle ({role}) MUSS event=`{target_event}` liefern (ausser bei Fehler: TASK_FAILED).\n"
            "- sender_role: PLANNER | CODER | VERIFIER | REVIEWER | SYSTEM  (hier: {role})\n"
            "- artifacts[].action: CREATE | UPDATE | DELETE\n\n"
        )
        parts.append("### Artefakt-Regeln\n")
        parts.append(
            "- Schreibe Artefakt-Dateien in `.pi/messenger/crew/` (relativ zu diesem Verzeichnis, "
            "z.B. `index.html`, `style.css`, `app.js`). KEINE absoluten Pfade, KEINE `..`.\n"
            "- Bei CREATE/UPDATE: `content` = null (der Firma-Receiver fuellt es aus der geschriebenen Datei).\n"
            "- Bei DELETE: `content` MUSS null sein.\n"
            "- `path` ist IMMER relativ zu `.pi/messenger/crew/`. KEINE absoluten Pfade, KEINE `..`.\n"
            "- Schreibe die Artefakt-Dateien VOR der Response-Datei.\n\n"
        )
        if role == "PLANNER":
            parts.append(
                "### plan_draft (nur PLANNER)\n"
                "`plan_draft` MUSS ein PlanDraftSchema sein (kein freier Text):\n"
                "```json\n"
                "{\n"
                '  "plan_name": "<name>",\n'
                '  "tasks": [{"id": "task-1", "description": "...", "dependencies": [], '
                '"expected_artifacts": [{"path": "<file>", "type": "CREATE"}], '
                '"acceptance_criteria": ["..."]}]\n'
                "}\n```\n\n"
                "**Der PLANNER schreibt KEINE Code-Dateien** — `artifacts` bleibt `[]`, "
                "die Dateien werden spaeter von der CODER-Rolle erzeugt.\n\n"
            )
        parts.append("### Reihenfolge (wichtig fuer den Receiver)\n")
        parts.append(
            f"1. Code-/Asset-Dateien relativ zum Crew-cwd schreiben (falls zutreffend).\n"
            f"2. `{resp_file}` vollstaendig + atomar schreiben (temp + rename).\n"
            f"3. Danach kehrst du zurueck. Firma erkennt die Response automatisch (Praesenz der Datei) - kein task.done noetig.\n\n"
        )
        parts.append("### Verboten (Invariante)\n")
        parts.append(
            "- KEINE Datenbank-/Dateisystem-Queries ausserhalb des Crew-cwd (Push-only, zustandslos).\n"
            "- KEINE absoluten Pfade / `..` in artifacts.\n"
            "- KEINE Reparatur eigener Fehler; bei Problem lieber `event=TASK_FAILED`.\n"
        )
        return "".join(parts)

    # ------------------------------------------------------------------ interface
    async def dispatch(self, payload: Dict[str, Any], review_artifacts: Optional[Dict[str, str]] = None) -> None:
        """Engine -> Worker. Materialisiert das Assignment als pi-messenger Task-File.

        Fire-and-forget: wir schreiben nur die Datei; das Starten der Worker
        erfolgt durch die Pi-Session (Harness) via pi_messenger({ action: 'work' }).
        """
        if payload.get("event") != "TASK_ASSIGNMENT":
            logger.warning(f"[PiMeshTransport] Ignoring non-assignment dispatch: {payload.get('event')}")
            return

        role = payload.get("role")
        if not role:
            raise ValueError("[PiMeshTransport] TASK_ASSIGNMENT without role")
        crew_cwd = self._crew_cwd(role)
        tasks_dir = self._tasks_dir(crew_cwd)
        os.makedirs(tasks_dir, exist_ok=True)

        task_id = payload.get("task_id")  # erwartet "task-N"
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        task = PiTaskFile(
            id=task_id,
            title=(payload.get("prompt") or "")[:80],
            status="todo",
            depends_on=[],
            created_at=now,
            updated_at=now,
            attempt_count=0,
            firma_assignment=payload,
        )
        # Atomar schreiben: task-N.json (Status) + task-N.md (Spec)
        self._atomic_write(
            os.path.join(tasks_dir, f"{task_id}.json"),
            json.dumps(task.to_dict(), indent=2, ensure_ascii=False),
        )
        self._atomic_write(
            os.path.join(tasks_dir, f"{task_id}.md"),
            self._build_spec_markdown(payload, review_artifacts),
        )
        logger.info(f"[PiMeshTransport] Dispatched {role} task {task_id} -> {tasks_dir}")

    async def publish_response(
        self, role: str, payload: Dict[str, Any], correlation_id: Optional[str] = None
    ) -> None:
        """Worker -> Engine. Packt Envelope und legt in interne Queue (wie InternalTransport)."""
        envelope = {
            "protocol_version": self.PROTOCOL_VERSION,
            "message_type": "WORKER_RESPONSE",
            "message_id": payload.get("message_id"),
            "role": role,
            "timestamp": payload.get("timestamp"),
            "correlation_id": correlation_id,
            "payload": payload,
        }

        async def ack():
            return None

        await self._queue.put(TransportMessage(envelope=envelope, _ack_handle=ack))

    async def poll(self) -> List[TransportMessage]:
        """Orchestrator-kompatibel: drain interne Queue."""
        msgs: List[TransportMessage] = []
        while not self._queue.empty():
            msgs.append(self._queue.get_nowait())
        return msgs
