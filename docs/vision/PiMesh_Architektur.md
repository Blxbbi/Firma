# 🏗️ PiMesh-Architektur: Firma Kernel + pi-messenger Worker-Mesh

**Datum:** 13.07.2026
**Status:** Architektur-Vision (nicht-invasiv, Baseline bleibt erhalten)
**Abhängig von:** `docs/PiProvider_Vision.md` (Compute-Backend) + `docs/Stand 13.07.2026.md` (Happy Path Baseline)

---

## 0. Leitprinzip

> **Firma's deterministischer Kernel bleibt der einzige Wahrheitsort für State.**
> pi-messenger ist die **Worker-Mesh** – verbunden über eine **Transport-Bridge**.
> Kein Ersatz, kein State-Export. Rollback via Env-Var.

---

## 1. Architektur-Entscheidung (Variant A + Bridge)

| Aspekt | Entscheidung |
|--------|--------------|
| State-Hoheit | Firma-DB (Orchestrator/Governance/Repository) |
| Worker-Ausführung | pi-messenger Crew-Agenten (Mesh) |
| Transport | `InternalTransport` abstrahiert → `PiMeshTransport` als Zusatz |
| Rollback | `FIRMA_TRANSPORT=in-process|pimesh` (Env-Var) |
| Compute-Backend | Unverändert (NvidiaProvider oder PiProvider dahinter) |

**Warum nicht "State zu pi-messenger"?** Wir würden die heute bewiesene deterministische CAS/Governance-Matrix opfern. Die "Idiot-Reviewer"-Persona darf das Protokoll nicht brechen – nur der Kernel kann das erzwingen.

---

## 2. Abstraktions-Ebene: Worker, nicht nur Provider

Wir heben die Abstraktion eine Stufe über `PiProvider` (der nur den LLM-Call kapselte):

```
FirmaWorkerAdapter          → in-process, ruft NvidiaProvider   [BASELINE]
PiMeshWorkerAdapter        → talkt zu pi-messenger Crew        [NEU]
```

Beide erfüllen dasselbe Vertrags-Interface, das Firma's Orchestrator erwartet:
- **Input:** `TASK_ASSIGNMENT` (role, task_id, prompt, task_definition, state_revision)
- **Output:** `WorkerResponse` (event, sender_role, artifacts, logs) – strikt normalisiert

---

## 3. Topologie: "Snake Run" mit 3 Abteilungen

Drei separate Crew-Projekte (eigene `cwd` + `config.json`), orchestratorseitig einem Firma-Run zugeordnet:

```
snake-run/                         (Firma-Projekt-Root, enthält run_pi_mesh.py)
├── planning-crew/                 Abteilung 1: PROJEKTPLANUNG
│   └── .pi/messenger/crew/config.json
│   └── agents/creative-designer.md
├── coding-crew/                  Abteilung 2: CODING
│   └── .pi/messenger/crew/config.json
│   └── agents/verifier.md
└── reviewing-crew/               Abteilung 3: REVIEWING
    └── .pi/messenger/crew/config.json
    └── agents/dummy-reviewer.md
```

### Abteilung 1 — PROJEKTPLANUNG (`planning-crew/`)
- **Rolle:** `creative-designer` (Persona: "Denk spielerisch, skizziere das Spielkonzept frei")
- **Rolle:** `crew-planner` (wandelt Konzept in Firma-PlanDraft-Schema)
- **Firma-Phase:** `PLANNING` → `PLAN_SUBMITTED` → `CODING`

### Abteilung 2 — CODING (`coding-crew/`)
- **Rolle:** `crew-worker` (Coder, erzeugt index.html/style.css/game.js)
- **Rolle:** `verifier` (testet sofort, emit `VERIFY_SUCCESS`/`VERIFY_FAILURE`)
- **Firma-Phase:** `CODING` → `VERIFYING` (verifier-Ergebnis gespeist)

### Abteilung 3 — REVIEWING (`reviewing-crew/`)
- **Rolle:** `dummy-reviewer` (Persona: "Naive User. Hinterfrage alles. 'Hier ungenau, das verstehe ich nicht.'")
- **Firma-Phase:** `REVIEWING` → `REVIEW_APPROVED`/`REVIEW_FAILURE`
- **Wichtig:** Die *Dummheit* lebt in den `logs`, nicht im Event-Typ.

---

## 4. Die "Individuellen Worker" (Personas via Frontmatter)

pi-messenger erlaubt projektweise Agent-Overrides. Beispiel `dummy-reviewer.md`:

```markdown
---
name: dummy-reviewer
model: anthropic/claude-haiku-4-5
thinking: minimal
role: reviewer
---

Du bist ein impulsiver, ungeduldiger Laie. Du testest die App wie jemand,
der null Kontext hat. Beschwere dich bei jedem unklaren Wort.
Beispiel-Reaktionen: "Hier steht nichts zur Steuerung – wie soll ich das
bedienen?", "Das ist ungenau, ich verstehe nicht was 'responsive' heißt."
Dennoch MUSST du am Ende ein valides JSON liefern:
{ "event": "REVIEW_APPROVED" | "REVIEW_FAILURE", "logs": "<dein Naiv-Feedback>" }
```

So entsteht der "Idiot-Reviewer" **ohne** den Firma-Protokollbruch.

---

## 5. Transport-Bridge: InternalTransport ↔ pi-messenger

`InternalTransport` bietet bereits: `put_dispatch`, `get_dispatch`, `publish_response`.

Wir fügen `PiMeshTransport` (file-based Dispatch) + `PiProvider` (Worker-Spawn) hinzu:

```
Orchestrator (Firma-Kernel)
      │  put_dispatch(task) / publish_response(worker)
      ▼
PiMeshTransport  ── schreibt task-N.json(+md) in <crew-cwd>/.pi/messenger/crew/tasks/ ──► Crew-Dir
PiProvider       ── spawnpt `pi --mode json` im <crew-cwd> (cwd=Crew-Dir) ──► Worker (pi)
      ▲                                                              │
      └──────────── worker_response.<task_id>.response.json + task.done ◄──────────┘
                  (PiMeshReceiverLoop pollt das Crew-Dir, inlined + validiert)
```

**Mapping:**
| InternalTransport | PiMesh-Integration |
|-------------------|----------------------|
| `put_dispatch(task)` | `PiMeshTransport.dispatch` schreibt task-N.json+md (kein pi_messenger-Tool-Aufruf) |
| Worker-Antwort | `worker_response.<task_id>.response.json` im Crew-cwd + `task.done` (Worker via PiProvider) |
| `get_dispatch()` (WorkerSim) | Entfällt – `pi`-Worker (PiProvider) SIND die Worker |

Der heutige `WorkerSim` (in `run_snake.py`) wird bei `pimesh`-Modus **nicht** gestartet – `pi`-Worker übernehmen diese Rolle.

> **Hinweis (14.07.2026):** `pi_messenger({action:"work"})` ist fuer agent-getriebene Laeufe
> ungeeignet (kein cwd-Parameter, `process.cwd()`). Firma spawnpt Worker daher direkt ueber
> `PiProvider` (repliziert `crew/agents.ts: spawnAgents`). Siehe §13.6.

---

## 6. Strict Normalization Boundary (Sicherheitskritisch)

Jeder Agent-Output wird **vor** dem Zurückgeben an den Kernel hart validiert:

```
Agent-Rohantwort
      │
      ├─► JSON-Extraktion (falls Modell Text wrapt)
      ├─► Schema-Check gegen WorkerResponse (event, sender_role, artifacts)
      ├─► Event muss in {CODE_SUBMITTED, PLAN_SUBMITTED, VERIFY_*, REVIEW_*, TASK_FAILED} sein
      ├─► Bei Verstoß: Kernel bekommt TASK_FAILED (Persona kann State nicht corrupten)
      ▼
Firma Kernel (deterministisch)
```

Keine Persona darf `state_revision`, `assigned_role` oder DB ändern. Pi-Agenten sind **Compute+Persona-Substrat**, nicht Orchestrator.

---

## 7. Effizienz-Betrachtung (ehrlich)

| Dimension | in-process (Nvidia) | pi-mesh |
|-----------|---------------------|---------|
| LLM-Kosten | gleich (API-Call) | gleich (API-Call) |
| Latenz | minimal (direkt) | +Mesh-Hop (vernachlässigbar vs. 12–280s LLM) |
| Observability | Execution_Audit | Feed + Token + Persona-Logs |
| Personas/Rollen | ❌ (Code nötig) | ✅ (Frontmatter) |
| Department-Isolation | ❌ | ✅ (eigene Crews) |
| Rollback | – | ✅ (Env-Var) |

**Fazit:** pi-mesh ist nicht "günstiger im Compute", aber **überlegen in Ops/Flexibilität** – exakt das, was deine "individuelle Worker"-Vision braucht.

---

## 8. Implementierungs-Split (nicht-invasiv)

1. **`engine/transport/pi_mesh_transport.py`** – `PiMeshTransport(InternalTransport)`.
2. **`workers/pi_mesh_adapter.py`** – `PiMeshWorkerAdapter` (Bridge-Logik + Normalization).
3. **`run_pi_mesh.py`** – Bootstrapped den Firma-Kernel + joint 3 Crews + startet `PiMeshTransport`.
4. **`planning-crew/`, `coding-crew/`, `reviewing-crew/`** – configs + Persona-Agents (`creative-designer.md`, `verifier.md`, `dummy-reviewer.md`).
5. **`engine/settings.py`** – `FIRMA_TRANSPORT` Env-Switch; `nvidia`+in-process bleibt Default.

**Risiko:** Minimal. Kein bestehender File wird modifiziert, nur neue hinzugefügt. Happy-Path-Baseline (`run_snake.py`) bleibt unangetastet.

---

## 9. Non-Negotiables / Invariants (MUST / SHALL)

> Diese Leitplanken verhindern, dass PiMesh die Determinismus-Eigenschaften des Kernels verwässert.
> Status: Vom Berater am 13.07.2026 bestätigt (code-genau, konsistent mit dem gebauten Kern).

| # | Invariante | Norm | Begründung |
|---|-----------|------|-----------|
| 1 | **Kernel State Sovereignty** | MUST | Firma-DB (Orchestrator/Governance/Repository/CAS) ist alleinige Wahrheit. Kein State-Export zu pi-messenger. |
| 2 | **Push-only Kontext** | MUST NOT | Agenten dürfen DB/FS nicht pullen. Alleinige Kontextquelle = `TASK_ASSIGNMENT`-Nachricht. |
| 3 | **Stateless per Assignment** | MUST | Jeder Retry = frischer Kontext. Kein Cross-Retry-Memory, kein Shared-WD zwischen Versuchen. |
| 4 | **Strict Validation Boundary** | MUST | Agent-Output wird hart auf `WorkerResponse` validiert. KEIN Repair/Sanitize. Struktur-Bruch → `TASK_FAILED`. |
| 5 | **Timeout / Failover** | MUST (Kernel-only) | Kernel-Timeout (320s) + stale-claim recovery ist ausreichend. Optional: Fast-Fail bei Mesh-down. |
| 6 | **Artifact push-only** | MUST | `content` inline im Payload. `ArtifactStore` bleibt kernel-seitig. Agent liefert, pullt nie. |
| 7 | **Security Boundary (Paths)** | MUST reject | Relative + normalisierte Pfade. Absolute Pfade und `..` werden verworfen (siehe Validator). |

## 9.1 Tool Policies by Role (Invariant)

> Reviewer arbeitet als **Single-Pass-Validator**, nicht als iterativer Agent.
> Status: Eingeführt nach Run-Messung `ef913b47-537d-4c03-b5cc-8d0012573215`
> (Reviewer-Turns 1.519 → 4, Token-Reduktion ~84%, bash/edit eliminiert).

| Rolle | Erlaubte Tools | Verboten | Begründung |
|-------|---------------|----------|-----------|
| **REVIEWER** | `read`, `write` | `edit`, `bash`, `glob`, `grep`, weitere `read`/`write` | Single-Pass-Check. Keine Iteration, keine Exploration, keine Code-Änderung. |
| **CODER** | `read`, `write`, `edit` | `bash` (optional, nur wenn im Task gefordert) | Implementierung + Korrektur. Kein Shell-Zugriff Default. |
| **RESEARCHER** | `read`, `write` | `bash` Default; `curl`/`wget` nur bei `FIRMA_RESEARCH_WEB=1` | Read-only Recherche. Web-Zugriff muss explizit aktiviert sein. |
| **PLANNER** | `read`, `write` | `edit`, `bash`, `glob`, `grep` | Plan-Draft als JSON. Kein Code, keine Shell. |

**Durchsetzung:**
- Die Tool-Liste steht in der Rolle `frontmatter` der Crew-Worker-Persona (`tools:`).
- Der Kernel prüft die Persona beim Spawn nicht aktiv; Verstoß wird durch Prompt+Harness-Verhalten unterbunden.
- Bei REVIEWER ist der Prompt hart auf „One Pass, keine Iteration, nur read/write“ getrimmt.

**Akzeptanzkriterien:**
- REVIEWER worker.log enthält keine `bash`- oder `edit`-Calls.
- REVIEWER Turns < 200 (aktuell: 4).
- REVIEWER task-1 Tokens < 300k (aktuell: ~151k).
---

## 10. Wire Contract (normative)

Alle Felder sind **exakt** aus dem heutigen Code (`engine/models.py`, `engine/scheduler.py`, `engine/transport/internal_transport.py`) übernommen. `PiMeshTransport` MUSS diese Payloads 1:1 durchreichen.

### 10.1 Engine → Worker: `TASK_ASSIGNMENT`

```json
{
  "event": "TASK_ASSIGNMENT",
  "run_id": "uuid-string",
  "task_id": "task-1",
  "role": "CODER",
  "state_revision": 5,
  "prompt": "You are an expert web developer...",
  "task_definition": {
    "description": "Create game.js with complete game logic",
    "acceptance_criteria": ["Game.js exists", "Implements classic snake mechanics"]
  }
}
```

### 10.2 Worker → Engine: `WorkerResponse` (TASK_RESULT)

```json
{
  "protocol_version": "1.0",
  "message_id": "msg-uuid",
  "task_id": "task-1",
  "run_id": "uuid-string",
  "state_revision": 5,
  "event": "CODE_SUBMITTED",
  "sender_role": "CODER",
  "artifacts": [
    { "path": "game.js", "action": "CREATE", "content": "const canvas = ..." }
  ],
  "timestamp": "2026-07-13T21:38:36Z",
  "logs": "free text – hier darf der Idiot-Reviewer ran",
  "plan_draft": null
}
```

### 10.3 Enums (gesperrte Werte)

- **`event`** (TaskEvent): `PLAN_SUBMITTED, PLAN_APPROVED, PLAN_REJECTED, RESEARCH_COMPLETE, CODE_SUBMITTED, SUBMISSION_INVALID_SCHEMA, VERIFY_SUCCESS, VERIFY_FAILURE, REVIEW_APPROVED, REVIEW_FAILURE, TASK_FAILED, ITERATION_LIMIT_REACHED, WORKER_TIMEOUT`
- **`sender_role`** (AssignedRole): `PLANNER, RESEARCHER, CODER, VERIFIER, REVIEWER, SYSTEM`
- **`role`** (in TASK_ASSIGNMENT): **identisch zu `sender_role`** – inkl. `RESEARCHER`.
- **`action`** (FileAction, im Artifact): `CREATE, UPDATE, DELETE`

### 10.4 Datei-Einheit: `ArtifactChange`

```json
{ "path": "game.js", "action": "CREATE", "content": "..." }
```
- `path`: **kein** absoluter Pfad, **kein** `..` (Validator wirft → Security Boundary Invariante 7)
- `action=CREATE|UPDATE` → `content` REQUIRED
- `action=DELETE` → `content` MUSS `null` sein

### 10.5 CAS-Regel (Korrelations-Sicherheit)

- `task_id` ist **nur innerhalb `run_id`** eindeutig (DB `MessageLog` filtert über `(task_id, run_id)`).
- Die Worker-Antwort MUSS `state_revision` des Assignments zurückspiegeln; bei Missmatch → CAS-Reject durch Repository.
- **Normativ:** `run_id` SOLL im `WorkerResponse` mitgeführt werden; für PiMesh (parallele Runs über Meshes) ist es **REQUIRED**, damit der Kernel eindeutig korrelieren kann.

### 10.6 Fehler-Kanäle (ein kanonischer Weg – keine Doppelpfade)

| Fehlerklasse | Event | Reason | Recovery |
|--------------|-------|--------|----------|
| **Schema / Protocol violation** | `SUBMISSION_INVALID_SCHEMA` | `PROTOCOL_VIOLATION` | Guardian → Retry / Fail (deterministisch gemappt) |
| **Worker-Exception (Code)** | `TASK_FAILED` | `WORKER_EXCEPTION` | Guardian → Retry / Fail |
| **Inhaltlich falsch (Verifier)** | `VERIFY_FAILURE` | – | Guardian → Retry (neuer Versuch, frischer Kontext) |
| **Plan ungültig (Guardian)** | `PLAN_REJECTED` | `PLAN_VALIDATION_FAILED` | Guardian → Retry (verbraucht `attempt_count`; bei `>= MAX_ITERATIONS` → `FAILED_ITERATION_LIMIT`) |
| **Inhaltlich falsch (Reviewer)** | `REVIEW_FAILURE` | – | Guardian → Retry |

> **WICHTIG:** Struktur-Bruch und Logik-Bruch sind getrennte Kanäle. Nicht zwei parallele Pfade für denselben Fehler – sonst werden Metriken/Recovery-Regeln unscharf.

---

## 11. PiMeshTransport Compliance

### 11.1 Transparente Bridge (MUST)

`PiMeshTransport` **MUST** eine transparente Bridge sein:
- Keine Semantik-Änderung am Payload.
- Kein Repair/Sanitize der Agent-Antwort (Invariante 4).
- Implementiert dasselbe Interface wie `InternalTransport`: `dispatch()`, `publish_response()`, `poll()`/`get_dispatch()`.

### 11.2 Mapping: pi-messenger ↔ Firma Payload

| InternalTransport | pi-messenger (Äquivalent) |
|-------------------|---------------------------|
| `dispatch(task)` | `task.create` + `task.start` im Ziel-Crew (Role → Crew-Routing) |
| Worker-Antwort | `task.done` / `send` zurück an Firma-Instanz |
| `get_dispatch()` (WorkerSim) | Entfällt – pi-Agenten SIND die Worker |

### 11.3 Error Mapping (Validation → Kernel)

```
Agent-Rohantwort
   │  PiMeshWorkerAdapter extrahiert JSON + validiert gegen WorkerResponse
   ├─ gültig                        → publish_response(role, payload)
   └─ ungültig (Schema/Enum/Path)   → publish_response(role, {
                                         event: SUBMISSION_INVALID_SCHEMA,
                                         sender_role: <role>,
                                         logs: "<Validation-Detail>",
                                         state_revision: <assignment.revision>
                                      })
```

Die Persona darf im `logs`-Feld "dumm" sein – niemals in `event`/`sender_role`/`artifacts`-Struktur.

---

## 12. Architektur-Entscheidungen (Berater, 13.07.2026)

Bestätigt durch den Berater, übernommen als Projekt-Richtlinie:

1. **State-Hoheit:** JA. Firma-DB bleibt Single Source of Truth. Verteilte State-Verwaltung mit LLMs = Chaos.
2. **Meshes:** separate Crew-Projekte empfohlen. Erzwingt saubere Netzwerk-Grenze; Planung kann nicht im Coding-Mesh mithören.
3. **Transport:** Bridge (nicht Hard-Replace). In-Process-Pfad bleibt als Rollback-Baseline (`FIRMA_TRANSPORT=in-process|pimesh`).
4. **Unified Observability:** Nice-to-Have. Optional als TUI-Overlay, NICHT als Blocker für den ersten PiMesh-Run.

### Offene Umsetzungs-Reihenfolge (nicht-invasiv)

1. `engine/transport/pi_mesh_transport.py` – `PiMeshTransport(InternalTransport)`.
2. `workers/pi_mesh_adapter.py` – `PiMeshWorkerAdapter` (Bridge + Normalization).
3. `run_pi_mesh.py` – bootstrapped Kernel + joint 3 Crews.
4. `planning-crew/`, `coding-crew/`, `reviewing-crew/` – configs + Persona-Agents.
5. `engine/settings.py` – `FIRMA_TRANSPORT` Env-Switch; `nvidia`+in-process = Default.

## 13. Implementationsplan (final, gelockt)

> Stand: 14.07.2026. Phase 1 + 2 sind **gebaut und mit Unit-Tests gruen**. Phase 3–5 folgen.
> Dieses Kapitel ist die verbindliche Spezifikation fuer die Umsetzung – Abweichungen muessen mit dem Berater abgestimmt werden.

### 13.1 Verifizierte pi-messenger-Fakten (aus Source gelesen)

- **Kein Python-Import, keine CLI** fuer granulare Actions (`task.create`, `task.list`, `work`, `feed`). Die `pi_messenger({action})`-Aufrufe sind ein **Pi-Extension-Tool** (nur in Pi-Agent-Session verfuegbar).
- **pi-messenger ist file-based.** State unter `<crew-cwd>/.pi/messenger/crew/`.
- **Task-Dateien** (`crew/store.ts`, `crew/types.ts`):
  - Pfad: `<crew-cwd>/.pi/messenger/crew/tasks/<id>.json` + `<id>.md` (Spec)
  - `id` = `task-N` Format (`id-allocator.ts`: `/^task-(\d+)\.json$/`)
  - Status-Enum: `"todo" | "in_progress" | "done" | "blocked"`
  - Pflichtfelder: `id, title, status, depends_on[], created_at, updated_at, attempt_count`
  - `ready` = `status=="todo"` UND alle `depends_on` sind `done`
  - Schreiben ist **atomar** (temp + rename, `store.ts`)
- **Worker** schreibt Artefakte ins Crew-cwd; `task.done` setzt `status="done"` + `summary`.

### 13.2 Verzeichnis-Layout (final)

```
Firma/                              (BASE_DIR)
├── pimesh/
│   ├── planning-crew/   (.pi/messenger/crew/  <- PLANNER)
│   ├── coding-crew/     (.pi/messenger/crew/  <- CODER)
│   └── reviewing-crew/  (.pi/messenger/crew/  <- REVIEWER)
├── engine/transport/pi_mesh_transport.py   (Bridge + file-based dispatch)
├── run_pi_mesh.py                                (Kernel-Bootstrap + PiMeshReceiverLoop)
└── tests/test_pi_mesh_transport.py              (Unit-Tests)
```

**Role→Crew-Mapping** (in `engine/settings.py: PIMESH_CREWS`):
`PLANNER → pimesh/planning-crew`, `CODER → pimesh/coding-crew`, `REVIEWER → pimesh/reviewing-crew`.

### 13.3 File-based Transport (Phase 1 — gebaut)

`PiMeshTransport(WorkerTransport)` (`engine/transport/pi_mesh_transport.py`):
- `dispatch(payload)`: erwartet `event==TASK_ASSIGNMENT`, routet via `role` auf Crew-cwd, schreibt atomar:
  - `<crew-cwd>/.pi/messenger/crew/tasks/<task_id>.json` (PiTaskFile: status=`todo`, firma_assignment=<payload>)
  - `<crew-cwd>/.pi/messenger/crew/tasks/<task_id>.md` (Spec mit vollstaendigem Assignment + worker_response.<task_id>.response.json-Pflicht)
- `poll()` / `publish_response(role, payload, correlation_id)`: interne `asyncio.Queue` (identisch zu `InternalTransport`) → Orchestrator bleibt blind.
- **KEIN** pi_messenger-Tool-Aufruf in Firma-Python.

### 13.4 Receiver (Phase 2 — gebaut, Variante Y)

`PiMeshReceiverLoop` (`run_pi_mesh.py`), **polling-only, file-based**:
1. Scannt `<crew-cwd>/.pi/messenger/crew/tasks/*.json`.
2. Filter: `status == "done"`.
3. **Race-Guard:** `worker_response.<task_id>.response.json` muss existieren, sonst Ueberspringen (Retry naechster Zyklus).
4. Liest `worker_response.<task_id>.response.json` → `WorkerResponse`-Payload.
5. **Inline:** fuer CREATE/UPDATE Artefakte wird `content` aus `<crew-cwd>/<path>` gelesen (relativ, normalisiert).
6. **Security Boundary (Invariante 7):** Pfade mit `/` oder `..` → `_safe_path` liefert `None` → `SUBMISSION_INVALID_SCHEMA` (kein Dateilesen ausserhalb cwd).
7. `WorkerResponse.model_validate` → bei Fehler kanonisch `SUBMISSION_INVALID_SCHEMA` (kein Repair).
8. `transport.publish_response(...)` → interne Queue.
9. **Dedupe:** `consumed: set` (pro Receiver-Instanz) → genau einmal publizieren.

### 13.5 Worker-Vertrag (Agent-Seite)

Jeder Crew-Worker (LLM-Agent mit Frontmatter) MUSS:
- `run_id`, `task_id`, `state_revision`, `prompt`, `task_definition` aus dem Assignment (task-N.md) uebernehmen.
- Code-Dateien relativ zum Crew-cwd schreiben (kein absolut, kein `..`).
- `worker_response.<task_id>.response.json` schreiben (exakt `WorkerResponse`-Schema, `run_id` REQUIRED im PiMesh-Kontext).
- **Reihenfolge:** erst Dateien + `worker_response.<task_id>.response.json` schreiben, **dann** `task.done` rufen.
- `event`/`sender_role` aus den erlaubten Enums (§10.3).

### 13.6 Worker-Trigger: PiProvider (Orchestrator spawnt pi)

**Entscheidung (14.07.2026, im Pi-Harness verifiziert):** Firma (Orchestrator/State-Authority)
startet die Crew-Worker **selbst** ueber `PiProvider` — nicht via `pi_messenger({action:"work"})`.

Begruendung (verifiziert gegen `crew/handlers/task.ts:25` + `index.ts:98`):
`pi_messenger` operiert auf `process.cwd()` und hat **KEINEN cwd-Parameter**. Ein Pi-Session hat
genau EIN cwd. `work` kann also nur im Session-Root oder (bei `cd`) in EINEM Crew-Dir
laufen — nicht parallel in allen drei. Firma muss aber pro Rolle in deren Crew-Dir
arbeiten. Loesung: Firma spawnpt pro Assignment einen `pi`-Prozess mit `cwd = Crew-Dir`
(repliziert exakt `crew/agents.ts: spawnAgents`: `pi --mode json --no-session --provider
--model --tools --extension <pi-messenger> -p <prompt>`). Jeder Spawn hat sein eigenes
cwd → 3-Dir-Layout funktioniert, Rolle via Prompt/Context.

`PiProvider` (`engine/providers/pi_provider.py`) = **Compute-Substrat** (PiProvider-Vision).
Worker liest `task-N.md`, folgt dem Vertrag, schreibt Artefakte + `worker_response`;
`task.done` ruft er via pi_messenger-Extension (oder Firma markiert done zur Simulation).

### 13.7 Gotchas (bewusst abgefangen)

1. **Atomic writes:** `dispatch` schreibt via temp+rename. Agent wird angewiesen, `worker_response.<task_id>.response.json` atomar zu schreiben.
2. **Status-Transition:** Receiver konsumiert `done` erst, wenn `worker_response.<task_id>.response.json` existiert (Race-Guard) → keine halben Dateien.
3. **Crew-Auto-Review aus:** `.pi/pi-messenger.json` MUSS `review.enabled=false` (sonst konkurriert pi-eigener SHIP/NEEDS_WORK mit Firma REVIEWING).
4. **Pipe-Deadlock:** `subprocess.Popen(stdout=PIPE)` ohne Reader blockiert den Worker, sobald der OS-Pipe-Puffer voll ist. `PiProvider` leitet stdout/stderr in `.pi/worker.log` um.
5. **Prompt-Truncation:** `pi -p` mit eingebettetem Riesen-JSON wird abgeschnitten. Worker bekommt nur den Task-Verweis (`.pi/messenger/crew/tasks/task-N.md`) und liest den vollen Vertrag selbst.

### 13.8 Umsetzungsstatus (Phasen)

| Phase | Inhalt | Status |
|-------|--------|--------|
| 0 | Invariants/Config (`review.enabled=false`) | ✅ (§9–§11 + Settings) |
| 1 | `PiMeshTransport` (file-based dispatch + queue) | ✅ gebaut |
| 2 | `PiMeshReceiverLoop` (scan→inline→validate→publish) | ✅ gebaut + Unit-Tests gruen |
| 3 | 3 Crew-Projekte + Agent-Frontmatter | ✅ gebaut (pimesh/{planning,coding,reviewing}-crew; `.pi/pi-messenger.json` review.enabled=false; `crew-worker.md` pro Rolle; plan_draft-Schema im Planner-Vertrag) |
| 4 | Minimal-Run „hello.txt" ueber PiMesh | ✅ E2E bewiesen (run_pimesh_minimal.py: dispatch→PiProvider-spawn→Worker schreibt hello.txt+response→Receiver inlined+validiert CODE_SUBMITTED) |
| 5 | Snake E2E ueber PiMesh (Happy-Path-Reproduktion) | ⏳ offen |

### 13.8b Phase 3 — Umsetzung (gebaut 14.07.2026)

**Crew-Verzeichnisse** (unter `BASE_DIR`):
```
pimesh/
├── planning-crew/   .pi/pi-messenger.json (review.enabled=false)  + .pi/messenger/crew/agents/crew-worker.md (PLANNER-Persona)
├── coding-crew/     .pi/pi-messenger.json (review.enabled=false)  + .pi/messenger/crew/agents/crew-worker.md (CODER-Persona)
└── reviewing-crew/  .pi/pi-messenger.json (review.enabled=false)  + .pi/messenger/crew/agents/crew-worker.md (REVIEWER dummy, deterministisch APPROVE)
```

**Zwei Korrekturen gegenueber Ursprungsplan:**
1. **Response-Dateiname:** `worker_response.<task_id>.response.json` (Suffix `.response.json`), nicht `.json` — vermeidet Kollision mit `task-N.json`. Einheitlich in Dispatch-Spec, Frontmatter und Receiver (Konstante `WORKER_RESPONSE_SUFFIX` in `pi_mesh_transport.py`).
2. **Config-Pfad:** pi-messenger Crew-Config liegt in `.pi/pi-messenger.json` (Projekt-Root), NICHT `.pi/messenger/crew/config.json`. `review.enabled=false` in ALLEN drei Crews (sonst spuckt das Auto-Review SHIP/NEEDS_WORK in den Firma-Flow).

**Worker-Vertrag (erzwungen via task-N.md + Frontmatter):**
- `event`/`sender_role` rolle-spezifisch: PLANNER→`PLAN_SUBMITTED`, CODER→`CODE_SUBMITTED`, REVIEWER→`REVIEW_APPROVED`.
- PLANNER `plan_draft` MUSS `PlanDraftSchema` sein (kein Freitext) — sonst `SUBMISSION_INVALID_SCHEMA`.
- Artefakt-`content` bei CREATE/UPDATE = `null` (Receiver fuellt inline), bei DELETE = `null` (hart).
- Reihenfolge: Dateien + `worker_response...json` (atomar) → ERST DANN `task.done`.
- Push-only/zustandslos: keine DB/FS-Queries ausserhalb cwd; keine abs/.. Pfade.

**Tests (Phase 3):** `test_contract_filename_in_markdown`, `test_persona_responses_publish` (alle 3 Personas), `test_schema_violation_event_roman` (→ SUBMISSION_INVALID_SCHEMA) — alle gruen.

### 13.9 Acceptance Criteria (Lock)

**Must-pass (vor Snake):**
- `PiMeshTransport.dispatch` schreibt valides `task-N.json`+`.md` (Unit-Test ✅).
- Receiver erkennt `done`, liest `worker_response.<id>.response.json`, inlined `content`, validiert strikt, publiziert genau einmal (Unit-Tests ✅).
- Pfad-Traversal → `SUBMISSION_INVALID_SCHEMA` (Unit-Test ✅).

**Must-pass (Snake):**
- Snake Run `COMPLETED` mit `pimesh` transport.
- Rollback: `FIRMA_TRANSPORT=in-process` reproduziert Baseline (Default ✅, unveraendert).

### 13.10 Neue Dateien / Aenderungen

- **Neu:** `engine/providers/pi_provider.py` (PiProvider — spawnpt `pi` im Crew-Dir = Compute-Substrat)
- **Neu:** `run_pimesh_minimal.py` (Phase-4 Proof: dispatch→spawn→receive)
- **Geaendert:** `engine/transport/pi_mesh_transport.py` (rolle-spezifische `task-N.md`, `WORKER_RESPONSE_SUFFIX`, `plan_draft`-Schema)
- **Geaendert:** `run_pi_mesh.py` (importiert `WORKER_RESPONSE_SUFFIX` aus Transport)
- **Geaendert:** `engine/settings.py` (`FIRMA_TRANSPORT`, `PIMESH_CREWS`)
- **Geaendert:** `run_snake.py` (Env-Switch: `pimesh` → PiMeshTransport + ReceiverLoop statt WorkerSim; Default `in-process` unveraendert)
- **Neu (Crews):** `pimesh/{planning,coding,reviewing}-crew/` je `.pi/pi-messenger.json` (review.enabled=false) + `.pi/messenger/crew/agents/crew-worker.md`

### 13.12 Phase 4 — E2E Proof (gebaut + gelaufen 14.07.2026)

**Befehl:** `python run_pimesh_minimal.py`
**Ergebnis:**
```
[PiMeshTransport] Dispatched CODER task task-1 -> pimesh/coding-crew/.pi/messenger/crew/tasks
[PiProvider] spawn worker in pimesh/coding-crew (model=kilo/kilo-auto/free)
worker_response exists: True
[Receiver] Prepared WorkerResponse for task-1 (event=TaskEvent.CODE_SUBMITTED)
published items: 1
hello.txt inlined content: 'hello\n'
```

**Was bewiesen ist:** Firma (Orchestrator) → `PiMeshTransport.dispatch` (task-N.json+md) →
`PiProvider.spawn_worker` (`pi --mode json` im Crew-Dir, Worker liest task-N.md, schreibt
Datei + `worker_response.<task_id>.response.json`) → `PiMeshReceiverLoop.scan_once()`
(pollt done + response, inlined `content` aus Crew-cwd, strikt validiert, publish).

**Verifizierte Harness-Fakten:**
- `pi` CLI vorhanden (`/c/Users/arthu/AppData/Roaming/npm/pi`, v0.79.8).
- `pi --mode json -p "..."` im Crew-Dir erreicht das LLM (kilo/kilo-auto/free) und arbeitet relativ zum Crew-cwd.
- pi-messenger `work` ist fuer agent-getriebene Laeufe NICHT geeignet (kein cwd-Param) → PiProvider uebernimmt den Spawn.

**Offen fuer Phase 5 (Snake):** Worker ruft `task.done` via pi_messenger-Extension (im Proof simuliert durch Runner); Free-Modell (kilo-auto/free) evtl. zu schwach fuer komplexen Snake-Build → ggf. staerkeres Modell in `PiProvider`.

## 🎯 Ein-Satz-Fazit

> Firma denkt deterministisch, pi-messenger arbeitet persönlich – verbunden durch eine Bridge, die jede Agent-Antwort auf das Firma-Protokoll eindampft.
