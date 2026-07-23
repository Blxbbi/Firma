# 📋 Briefing: Projekt "Firma" – Status, Erkenntnisse & PiMesh-Vision

**Erstellt:** 13.07.2026
**Zweck:** Vollständige Einweisung des Beraters in den aktuellen Stand, die gewonnenen Erkenntnisse und die geplante pi-messenger-Integration.
**Zielgruppe:** Externer Architektur-Berater (kein Chat-Kontext nötig)
**Verwandte Docs:** `Stand 13.07.2026.md`, `PiProvider_Vision.md`, `PiMesh_Architektur.md`

---

## 1. Executive Summary (TL;DR)

"Firma" ist eine **deterministische AI-Execution-Engine**: Sie zerlegt einen Ziel-Prompt in Tasks, lässt LLMs Code erzeugen, verifiziert das Ergebnis strikt und wiederholt bei Fehlern – alles über eine governance-gesteuerte State-Machine.

**Heute (13.07.):** Wir haben den ersten vollständigen End-to-End-Erfolg ("Happy Path") erzielt: Aus dem Prompt *"Snake Game"* entstand ein spielbares Spiel, der Run erreichte `COMPLETED`.

**Kern-Erkenntnis:** Die vermeintliche "Cognitive Laziness" des Modells war zu 100% ein **Context-Loss-Bug im Datenfluss**, kein Modell-Problem.

**Nächster Schritt (Vision):** Die Worker (Planner/Coder/Reviewer) sollen von in-process Python-Klassen zu **pi-messenger-Agenten in Meshes** werden – organisiert in Abteilungen (Planung/Coding/Review), mit individuellen "Personas" (z.B. ein bewusst "naiver" Reviewer). Firma's deterministischer Kern bleibt der Alleinherrscher für State.

---

## 2. Was ist "Firma"? (Architektur-Grundlagen)

Firma folgt dem Prinzip **"Correct by Design"**: Eine deterministische Hülle um probabilistische LLMs.

### Die Schichten

| Schicht | Verantwortung | Zustand |
|---------|---------------|---------|
| **Orchestrator** | Tick-Loop, Phasen-Guard, Hard-Timeout | Kern |
| **Governance-Matrix** | Erlaubt welche Events welche Phasen/Role-Übergänge | Kern |
| **Repository (DB)** | Tasks, CAS-Revisionen, Transition-Log | Kern |
| **Guardian** | Retry-Budget, Iteration-Limit, Verifier-Trigger | Kern |
| **ExecutionService + Verifier** | Strukturelle Prüfung (z.B. Canvas vorhanden?) | Kern |
| **ArtifactStore** | Filesystem-Versionierung der Artefakte | Kern |
| **Scheduler** | Weist READY-Tasks einer Role zu | Kern |
| **Transport (InternalTransport)** | In-process Message-Queue zwischen Engine ↔ Worker | **Pipe** |
| **Workers (Planner/Executor)** | Rufen LLM auf, liefern Artefakte | **Pipe** |
| **Provider (Nvidia)** | LLM-API-Call (JSON-Mode) | **Pipe** |

**Wichtig:** Alles bis auf die letzte Gruppe (Pipe) ist der **deterministische Kern**, den wir über Wochen stabilisiert haben.

### Schlüsselbegriffe
- **CAS (Compare-And-Swap):** Jede Task hat eine `state_revision`. Worker dürfen nur antworten, wenn ihre Revision aktuell ist – verhindert Race-Conditions.
- **Governance-Matrix:** `{(Phase, Event) → (NextPhase, NextRole)}`. Kein Event passiert ohne autorisierte Transition.
- **Narrator:** Schreibt menschenlesbare Phase-Banner/Events statt Dictionary-Dumps.
- **Verifier:** Prüft Artefakte hart (z.B. `<canvas>` in HTML, Game-Loop in JS) vor Akzeptanz.

---

## 3. Heutiger Stand: Was wir HABEN (Stand 13.07.2026)

### 3.1 Happy Path SUCCESS bewiesen
Run `d896c1bd-44ee-4a11-b42b-f657fe1a088a` erreichte **terminal state: COMPLETED**.
Alle Tasks durchliefen: `PLANNING → CODING → VERIFYING → REVIEWING → COMPLETE`.

### 3.2 Das Produkt (echtes Snake-Spiel)
- Assemblierte Version: `deliverables/snake_game/` (`index.html`, `style.css`, `game.js`)
- Engine-versioniert: `data/artifacts/d896c1bd-.../task-{1,2,3}/`
- Milestone (gegen Verlust): `milestones/happy_path_13_07_2026/`

### 3.3 Stabile Runtime (aus vorigen Sessions)
Folgende Schwächen sind bereits eliminiert: Silent Hangs, State-Leaks, Zombie-Tasks, Retry-Explosionen, Provider-Freeze, deterministische Recovery.

---

## 4. Was wir HERAUSGEFUNDEN haben (Root-Cause-Analyse)

Vor dem heutigen Fix scheiterte der "Offensive Run" systematisch. Die Ursachen:

### Finding 1 — Context-Loss im Scheduler→Worker-Datenfluss
- `scheduler.py` sandte nur das Feld `prompt` (Global-Ziel), aber **nicht** `task_definition`.
- `run_snake.py` (WorkerSim) las `msg.get("task_definition", {})` → bekam **`{}`**.
- Der Executor baute einen Prompt `"Task Definition: {}"` → das Modell wusste nicht, was es bauen soll.
- **Folge:** "Hello World"-Skelette statt Snake-Game.

### Finding 2 — Context-Fragmentierung im Executor-Prompt
- Ein schwaches Few-Shot-Beispiel (zeigte `<h1>`) primte das Modell auf Minimal-Output.
- Das Modell kannte bei einem Micro-Task ("Schreibe style.css") den Gesamtzweck (Snake Game) nicht.

### Finding 3 — Verifier-Over-Specification
- `web_verifier.py` suchte JS-Code (`requestAnimationFrame`, `speed`) im **HTML-File** → schlug immer fehl.
- Zusätzlich verlangte er das Wort `speed`/`velocity` (Over-Spec), obwohl `setTimeout(...,100)` reicht.

### Finding 4 — Hardcodierter 150s-Timeout + fehlender Reviewer
- `orchestrator.py` hatte `HARD_TIMEOUT = 150s` hartkodiert. NVIDIA-Latenz-Anomalie: 281s → Crash.
- `run_snake.py` behandelte nur `PLANNER`/`CODER`, nicht `REVIEWER` → nach allen Tasks Hang in `REVIEWING`.

**Harte Lektion:** "Cognitive Laziness" des Modells war ein Plumbing-Bug, kein Intelligenz-Problem.

---

## 5. Was wir GETAN haben (Die 4 Fixes)

| # | Fix | Datei | Effekt |
|---|-----|------|--------|
| 1 | `task_definition` im Dispatch mitsenden | `scheduler.py` | Worker kennt Subtask |
| 2 | Context-Injection im Prompt (Goal+Subtask+Anti-Laziness+Verifier-Expectations) | `executor.py` | Modell schreibt echtes Spiel |
| 3 | Task-bewusster Verifizierer (Canvas/Loop/Input gezielt) | `web_verifier.py` | Verifikation passiert bei echtem Code |
| 4 | Timeout 320s + `REVIEWER`-Simulation | `orchestrator.py`, `scheduler.py`, `base.py`, `nvidia_provider.py`, `run_snake.py` | Kein Crash, sauberer Phasen-Durchlauf |

**Parameter (vom Berater vorgegeben, eingehalten):**
- Iteration-Limit: **3** (statt 5)
- Timeout: auf **320s** (Governance) / **300s** (Provider) angehoben, "max aber nicht mehr"
- Modell: **Llama 3.1 70B** (bewusst beibehalten, um Context-Fix zu beweisen)

---

## 6. Die PiMesh-Vision: Was wir WOLLEN

### 6.1 Motivation
Wir wollen die LLM-Worker nicht mehr als in-process Python-Klassen, sondern als **pi-messenger-Agenten in Meshes** – weil wir dadurch:
- Abteilungen (Planung/Coding/Review) isolieren können
- **Individuelle Worker-Personas** definieren (z.B. einen "dummen" Reviewer)
- Native Observability (Token, Prompts, Feed) bekommen
- Flexibel Module ein-/ausbauen

### 6.2 Topologie: "Snake Run" mit 3 Abteilungen
```
planning-crew/    → creative-designer + crew-planner     (Abt. 1: Projektplanung)
coding-crew/      → crew-worker + verifier                (Abt. 2: Coding + Test)
reviewing-crew/   → dummy-reviewer (naive User-Persona)  (Abt. 3: Reviewing)
```

### 6.3 Individuelle Worker (Beispiel "Idiot-Reviewer")
Über pi-messenger-Agent-Frontmatter definieren wir Personas. Der `dummy-reviewer` bekommt die Anweisung: *"Du bist ein naiver User. Hinterfrage alles. 'Hier ist ungenau, das verstehe ich nicht.'"*
**Wichtig:** Seine *Dummheit* lebt in den `logs`, nicht im Event-Typ. Er muss trotzdem `REVIEW_APPROVED`/`REVIEW_FAILURE` emitten – das Protokoll bleibt intakt.

### 6.4 Architektur-Entscheidung: Variante A (Bridge, nicht Replace)
- **Firma-Kernel bleibt einziger Wahrheitsort** für State (DB/CAS/Governance).
- pi-messenger wird zur **Worker-Mesh**, verbunden über `PiMeshTransport` (implementiert dasselbe Interface wie `InternalTransport`).
- Rollback via Env-Var `FIRMA_TRANSPORT=in-process|pimesh`.
- `InternalTransport` (in-process) und `PiMeshTransport` (mesh) sind austauschbare Implementierungen.

---

## 7. Vorteile der PiMesh-Vision

| Vorteil | Erklärung |
|---------|-----------|
| **Personas/Rollen** | Worker individuell konfigurierbar (Designer, dummer Reviewer) via Frontmatter – heute nur per Code möglich |
| **Department-Isolation** | 3 separate Crews = saubere Trennung, eigene Modelle pro Rolle |
| **Observability** | pi-messenger-Feed, Token-Tracking, Live-Task-Progress im TUI-Overlay |
| **Modularität** | Crews/Worker ein-/ausbaubar ohne Kern-Eingriff |
| **Rollback** | in-process-Baseline bleibt als Sicherheitsnetz |
| **Kein Kern-Risiko** | Deterministische Governance wird nicht angerührt |

---

## 8. Was wir BEHALTEN (Kern – unantastbar)

- `engine/orchestrator.py` (Tick, Phasen-Guard, Timeout)
- `engine/governance.py` (State-Machine)
- `engine/repository.py` (DB, CAS, Revisionen)
- `engine/services/guardian.py` (Retry, Iteration-Limit)
- `engine/services/execution.py` + `verifiers/*` (strukturelle Prüfung)
- `engine/services/artifact_store.py` (Versionierung)
- `engine/models.py` (Schemas)
- `engine/controller.py` (Lifecycle)
- `run_snake.py` + Provider + Workers (**als Rollback-Baseline**)

## 9. Was wir ÄNDERN/ERSETZEN (Pipe – nicht hart löschen)

| Komponente | Wird zu | Modus |
|------------|---------|------|
| `internal_transport.py` | `pi_mesh_transport.py` | parallel (Env-Switch) |
| `workers/planner.py`, `executor.py` | pi Crew-Agenten | parallel |
| `engine/providers/*` | LLM-Call wandert in pi-Agent | ruht im pimesh |
| `run_snake.py` WorkerSim | `run_pi_mesh.py` | parallel |

---

## 10. Risiken & Worauf zu achten

| Risiko | Mitigation |
|--------|-----------|
| **Persona korrumpiert State** | Strict Normalization Boundary: Agent-Output wird hart auf `WorkerResponse`-Schema validiert; bei Verstoß → `TASK_FAILED` |
| **State-Export zu pi-messenger** | VERBOTEN (Variante A). Firma-DB bleibt alleinige Quelle |
| **Mesh-Latenz** | Vernachlässigbar vs. 12–280s LLM-Call; Provider-Timeout 300s bleibt |
| **pi-messenger nicht als pip-Paket** | Firma-Kernel muss im pi-Harness-Kontext laufen (Child-pi / pi_messenger-Tool) |
| **Fragmentierte Observability** | Zwei Kanäle (Firma-Konsole + pi-Feed); korrelierte Timeline = optionaler Mehrbau |

---

## 11. Offene Fragen / Entscheidungen für den Berater

1. **State-Hoheit:** Einverstanden, dass Firma-DB alleinige Quelle bleibt? (Empfehlung: Ja)
2. **Meshes:** Buchstäblich separate Crew-Projekte pro Abteilung, oder logische Trennung? (Empfehlung: separate Crews)
3. **Transport:** Bridge (beide parallel) oder hard Replace? (Empfehlung: Bridge + Rollback)
4. **Unified Observability:** Soll eine korrelierte Timeline (Firma-Event + pi-Agent) gebaut werden? (Nice-to-have)

---

## 12. Referenzen & Artefakte

| Pfad | Inhalt |
|------|--------|
| `docs/Stand 13.07.2026.md` | Tagesbericht Happy Path |
| `docs/PiProvider_Vision.md` | Compute-Backend Vision (Vorstufe) |
| `docs/PiMesh_Architektur.md` | Detaillierte 3-Crew-Topologie + Bridge-Design |
| `milestones/happy_path_13_07_2026/` | Gesicherter Code + Produkt-Snapshot |
| `deliverables/snake_game/` | Spielbares Snake-Spiel |
| `data/artifacts/d896c1bd-.../` | Engine-versionierte Artefakte des erfolgreichen Runs |

---

## 🎯 Ein-Satz-Zusammenfassung für den Berater

> Firma denkt deterministisch (bewiesener Happy Path), pi-messenger arbeitet persönlich (individuelle Agenten in Abteilungen) – verbunden durch eine Bridge, die jede Agent-Antwort auf das Firma-Protokoll eindampft. Wir werfen den Kern nicht weg, nur die Leitung.
