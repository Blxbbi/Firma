# Modi: Deterministic vs. Collaborative (Persistent Agent Sessions)

**Status:** Design-Dokument (noch nicht implementiert)
**Ziel:** Dem Berater die Architektur-Entscheidung „stateless Worker (heute) vs.
lebendige, vernetzte Agent-Sessions (Collaborative Mode)" klar vermitteln — inklusive
`pi`-Mechanik, Datenfluss, FSM-Interaktion und Tradeoffs.

---

## 0. TL;DR (für den Berater)

- Firma spawn-t heute echte `pi`-Subprozesse pro Assignment, aber **one-shot** (`-p`):
  der Worker baut sein Artefakt, schreibt die Response-Datei, und `pi` **endet**.
- Das ist eine **bewusste Design-Entscheidung** (Determinismus + Token-Planbarkeit),
  **keine** pi-Limitierung. `pi` kann sehr wohl **persistente Sessions** fahren.
- Der Wunsch: CODER- und REVIEWER-Sessions **lebendig lassen**, damit der Reviewer dem
  Coder „Schritt 3 ist falsch" sagen kann und der Coder seinen Kontext behält + fixxt.
  Theoretisch auch cross-department (CODER → PLANNER: „im Plan ist was doppelt").
- Antwort: Ja, machbar. `pi`-Instanzen sind normale Prozesse; wir müssen nur den
  **`-p`-One-Shot-Kill weglassen** und den Kernel als **Message-Bus** zwischen den
  lebendigen Sessions schalten. Das ist ein **dritter Modus** (collaborative), der
  zwischen dem heutigen stateless-Modus und dem voll-autonomen pi-messenger-Mesh steht.
- Tradeoff: Determinismus sinkt, Lifecycle/Kernel-Routing wird komplexer; Token-Kosten
  sind bei Iterations-Schleifen (Coder↔Reviewer) oft **niedriger** als neu-Spawnen.

---

## 1. Was wir HEUTE haben (stateless / fire-and-forget)

### 1.1 Spawn-Mechanik (IST)
`engine/providers/pi_provider.py` → `spawn_worker()`:
```python
args = [exe, "--mode", "json", "--no-session",
        "--provider", prov, "--model", mdl, "--tools", tools,
        "--extension", ext, "-p", prompt]          # ← -p = process & EXIT
proc = subprocess.Popen(args, cwd=crew_cwd,
                        stdout=log_f, stderr=subprocess.STDOUT)
# proc wird NICHT mehr beachtet → Worker endet nach einem Turn
```
`pi --help` bestätigt: `-p, --print` = *"Non-interactive mode: process prompt and exit"*.

### 1.2 Ablauf (IST)
```
Scheduler (READY→CLAIMED) → callback → transport.dispatch(task-N.md)
                                    → PiProvider.spawn_for_assignment()
                                        → `pi --mode json -p "…"`  (Subprozess)
Worker liest task-N.md, baut Dateien, schreibt worker_response.<id>.response.json
  → `pi` END ↔ Subprozess gekillt (Kontext des LLM-Chats weg)
Receiver pollt Datei → inline + validate → Guardian FSM
  → VERIFYING → REVIEWING → COMPLETE  (oder bei Fehler: neuer Spawn)
```
**Eigenschaft:** Jeder Worker ist zustandslos. Artifacts (das PRODUKT) überleben in
`data/artifacts/` + DB; der LLM-Conversation-State stirbt mit dem Prozess.

### 1.3 Warum wir das so gebaut haben (geratifiziert)
- **Kernel State-Sovereignty** (Berater-Empfehlung #1): nur Firma schreibt State.
- **Bridge not Hard-Replace** (#3): pi-messenger ist Compute-Substrat, nicht Orchestrator.
- Determinismus, Auditierbarkeit, planbare Token-Kosten.

---

## 2. Die drei Modi (Entscheidungsmatrix)

| Modus | Worker-Lebenszyklus | Kontext erhalten? | Determinismus | Token | Wann sinnvoll |
|-------|---------------------|-------------------|---------------|-------|---------------|
| **A. Deterministic** (heute) | fire-and-forget (`-p`, endet) | nein | hoch | planbar pro Task | Default, CI, Audit, Reproduzierbarkeit |
| **B. Collaborative** (neu) | **persistente Session**, Kernel routet Feedback | ja (Conversation) | mittel | bei Fix-Loops oft **günstiger** | Qualität, Coder↔Reviewer, iterative Builds |
| **C. Autonomous Mesh** (native pi-messenger) | Lobby/Mesh, freie Koordination | ja | niedrig | hoch (README warnt explizit) | offene Exploration, unstrukturierte Zusammenarbeit |

Modus B ist das, was der User will: Agenten bleiben leben und „reden", aber **Firma
bleibt der Switchboard** (kein peer-to-peer Mesh). Das respektiert alle 4 ratifizierten
Empfehlungen — es ist eine **Erweiterung des Bridge-Substrats**, kein Hard-Replace.

---

## 3. Collaborative Mode — Architektur (SOLL)

### 3.1 Pi-Session lebendig halten (konkret)
`pi --help` liefert die nativen Hebel:
```
--mode <mode>      text (default) | json | rpc
-p, --print        Non-interactive, process & EXIT   ← wir LASEN das weg
(ohne -p)          Interactive mode: mehrere Messages, Session bleibt resident
--session <id>     Session persistiert auf Disk (Context überlebt auch Prozess-Neustart)
--continue/-resume Session fortsetzen
--no-session       (heutig) ephemeral
```
**Spawn-Änderung:** statt `-p "<prompt>"` → interaktiver/rpc-Modus, **stdin offen
halten**, Initial-Prompt als erstes stdin-Message. `pi` endet nach einem Turn NICHT,
sondern wartet auf weiteres stdin. Der Worker schreibt wie gehabt `worker_response.<id>.response.json`
(Output-Contract unverändert) und kehrt in den Wartezustand zurück.

### 3.2 SessionRegistry (NEU)
`engine/providers/session_registry.py` (oder in `PiProvider`):
```python
SessionHandle = {
    run_id, task_id, role, department, persona_id,
    proc: subprocess.Popen,        # stdin offen, stdout→worker.log
    crew_cwd, idle_since, state,    # ALIVE | PARKED | STOPPED
}
registry: Dict[(run_id, task_id), SessionHandle]   # bzw. (department, persona)
```
Jeder lebendige Worker bekommt einen Handle. Die Registry ist **Infra/State des Kernels**
(kein pi-messenger-Shared-State) → Sovereignty bleibt bei Firma.

### 3.3 Message-Bus (Kernel als Switchboard) (NEU)
`engine/services/message_bus.py`:
- `route(target_task_id, message: str)` → schreibt `message` als neues User-Turn in die
  stdin des Ziel-Session-Handles.
- Subskribiert den JSONL-Stream (stdout) jeder Session, um Completion-Events
  (`worker_response.*.response.json` wird geschrieben) frühzeitig zu erkennen.
- **Cross-department:** CODER-Session emittiert z.B. `PLAN_ISSUE`-Event → Bus routet an
  PLANNER-Session (sofern lebendig). Agenten reden NICHT direkt miteinander, sondern über
  den Bus → saubere Trennung + Auditierbarkeit.

### 3.4 Lifecycle
| Trigger | Aktion |
|---------|--------|
| Task COMPLETE / FAILED | Session STOP (graceful: Stop-Message an stdin, dann SIGTERM nach Grace-Period) |
| Idle-Timeout (z.B. 300s keine Aktivität) | Session STOP (verhindert geleakte `pi`-Prozesse) |
| Run-Ende / `controller.stop_run` | Alle Sessions STOP |
| Während VERIFYING/REVIEWING | Session **PARKED** (resident, aber kein Input) — idle-timer pausiert |

### 3.5 FSM-Interaktion (wichtig: FSM bleibt erhalten)
Wir ändern NICHT die GovernanceMatrix. Wir ändern nur, **wer** den CODER-Turn ausführt:
- **Heute:** REVIEW_FAILURE → `transition_task_atomic(COMPLETE→CODING)` → Scheduler
  re-claimt → **neuer** `pi`-Spawn (frischer Kontext).
- **Collaborative:** REVIEW_FAILURE → FSM wie gewohnt zurück CODING, ABER der Kernel
  routet das Reviewer-Feedback **in die bereits lebendige CODER-Session** (relay statt
  Re-Spawn). Dieselbe Session fixxt Schritt 3, schreibt neue `worker_response`, der
  Receiver/FSM läuft weiter.

```
CODER-Session (lebt) ──CODE_SUBMITTED──▶ VERIFYING ─(fail)─▶ REVIEWING
                                                    │
                              Reviewer-Feedback ("Schritt 3 falsch")
                                                    │
                                    Message-Bus: stdin ──▶ CODER-Session (lebt weiter)
                                                    │
                              CODER fixxt, schreibt worker_response neu
                                                    │
                                          ──CODE_SUBMITTED──▶ VERIFYING … ▶ COMPLETE
```
→ **Audit/FSM identisch zum heutigen Modus**, nur der Worker ist nicht gestorben. Das ist
der Schlüssel: wir gewinnen Context-Retention OHNE die ratifizierte FSM aufzugeben.

---

## 4. Datenfluss-Diagramme

### 4.1 Coder↔Reviewer Loop (Collaborative) — der Kern-Wunsch
```
┌──────────────────── Firma-Kernel (State-Sovereignty) ────────────────────┐
│ Scheduler │ Guardian(FSM) │ Verifier │ Message-Bus │ SessionRegistry      │
└───────┬──────────────────────────────────────────────────────────────────┘
        │
   PLANNER-Session (lebt, p1) ──plan_draft──▶ Guardian: CODER-Tasks (CODING)
        │
   CODER-Session (lebt, c1, crew-cwd)  ◀── dispatch + spawn (einmalig)
        │  liest task-N.md, baut game.js (Schritt 1/2/3), schreibt worker_response
        │
   Receiver/Guardian ─▶ VERIFYING (Kernel-Verifier) ─▶ REVIEWING
        │
   REVIEWER-Session (lebt, r1) liest Artefakte, emittt REVIEW_FAILURE
        │   logs = "Schritt 3 hat einen Fehler: …"
        ▼
   Message-Bus.route(c1, "Reviewer-Feedback: Schritt 3 falsch → fixe nur 3, behalte 1/2")
        │
   CODER-Session c1 (behält Conversation!) ─▶ fixxt Schritt 3 ─▶ worker_response neu
        │
   Guardian: VERIFYING ─▶ REVIEWING ─▶ REVIEW_APPROVED ─▶ COMPLETE
        │
   Lifecycle: c1, r1, p1 Sessions STOP (Run COMPLETED)
```

### 4.2 Cross-Department: CODER → PLANNER (theoretisches Beispiel)
```
CODER-Session c1: "Im Plan ist Aufgabe X doppelt — ergibt keinen Sinn."
   │  emittiert PLAN_ISSUE { text, task_refs }
   ▼
Message-Bus.route(planner_session p1, "Coder meldet Doppelung in X …")
   │
PLANNER-Session p1 (lebt noch!): "Hmm, stimmt." → emittiert PLAN_REVISION
   │
Guardian: PLAN_REVISION → aktualisiert Plan (neue CODER-Tasks) — FSM-Erweiterung nötig
```
**Hinweis:** Das ist ambitionierter als 4.1, weil der PLANNER heute nach PLAN_SUBMITTED
COMPLETE ist. Es braucht entweder (a) den Planner-Session lebendig zu halten + ein
advisories (nicht-blockierendes) Routing, oder (b) ein neues Event `PLAN_REVISION`, das
die Plan-Phase (kontrolliert) wieder öffnet. **Empfehlung:** Zuerst 4.1 (Coder↔Reviewer)
umsetzen; 4.2 als nachgelagerte Erweiterung.

---

## 5. Tradeoffs (ehrlich)

| Dimension | Deterministic (heute) | Collaborative (neu) |
|-----------|-----------------------|---------------------|
| **Kontext-Retention** | nein (nur Artefakt-Dateien) | ja (volle Conversation des Workers) |
| **Coder↔Reviewer-Loop** | funktioniert, aber Coder kriegt Feedback NICHT injiziert (heutige Lücke, siehe §6) | nativ: Feedback in lebendige Session |
| **Tokens** | planbar; bei Retry: Task+Files neu erklärt | Retry spart Re-Explain → bei Fix-Loops **oft günstiger**; dafür Context pro Turn bezahlt |
| **Determinismus** | hoch (replaybar, CAS) | mittel (Session hängt von Verlauf ab) |
| **Reproduzierbarkeit** | ja | nein (gleicher Input ≠ gleicher Pfad) |
| **Ressourcen** | N kurze Prozesse | N residente `pi` + offene LLM-Contexts |
| **Lifecycle-Komplexität** | trivial (Prozess endet) | Bus + Registry + Stop/Idle nötig |
| **Auditierbarkeit** | voll (FSM + Logs) | voll (FSM + Bus-Log + worker.log pro Session) |

**Fazit zum User-Einwand „ohne Folgen":** Lebendige Sessions haben Folgen
(Lifecycle, Tokens, weniger Determinismus) — aber für iterative Builds (Coding/Reviewing)
ist der Token-Haushalt oft **besser**, weil das Re-Explain entfällt. Die Qualität
(CODER versteht Reviewer) steigt spürbar.

---

## 6. Heutige Lücke, die Collaborative schließt (Retry-Context-Injection)

Heute (stateless) wird Reviewer-Feedback in `_log_attempt` gespeichert, aber **nicht**
zurück in die Retry-Spec (`_build_spec_markdown` nutzt nur `task_definition`) injiziert.
→ Coder sieht beim Retry den Satz „Schritt 3 falsch" nie. Departments nur schwach verbunden.

Collaborative Mode löst das **ohne** die (stateless nötige) Retry-Injection: die Session
lebt, das Feedback wird via Bus in dieselbe Session geroutet. Die stateless-Variante
(Retry-Context-Injection) bleibt als Alternative bestehen, falls man bei Modus A bleibt.

---

## 7. Zusammenspiel mit Personas / Abteilungen (Paul & Anton)

Das `docs/Persona_Departments.md`-Konzept (Roster: Department → Personas mit eigener
System-Prompt-Datei) passt 1:1:
- Jede **Persona** = eine lebendige `pi`-Session mit ihrer `agent`-Datei
  (z.B. `pimesh/planning-crew/.pi/messenger/crew/agents/paul.md` = Web-Planner,
   `anton.md` = Game-Planner).
- `SessionRegistry` schlüsselt nach `(department, persona_id)`.
- Join/Leave = Persona in Roster `available:true/false` → Bus routet nur an verfügbare.
- Beispiel: Run „Snake" → Bus wählt `anton` (Game-Planner); Run „Landingpage" → `paul`.

Collaborative Mode + Personas = die vom User gewünschte Organisation:
**Abteilungen sind nicht abgeschottet, sondern über den Kernel-Bus verbunden, und jede
Abteilung hat benennbare, austauschbare Agenten mit eigener Identität.**

---

## 8. Einordnung in ratifizierte Berater-Empfehlungen

| # | Empfehlung | Status in Collaborative Mode |
|---|-----------|------------------------------|
| 1 | Kernel = alleiniger State-Owner | ✅ SessionRegistry/Bus sind Kernel-Infra; pi-messenger-Shared-State wird NICHT genutzt |
| 2 | separate Crew-Projekte | ✅ Personas = separate `agent`-Dateien pro Crew-Dir |
| 3 | Bridge not Hard-Replace | ✅ pi-messenger bleibt Substrat; kein autonomer Mesh-Orchestrator |
| 4 | Unified Observability (Nice-to-Have) | ◐ Bus-Log + worker.log pro Session liefern Live-Sicht; Dashboard optional später |

---

## 9. Implementierungs-Bausteine (konkret)

| Datei | Änderung |
|-------|----------|
| `engine/settings.py` | `FIRMA_MODE = "deterministic" | "collaborative"` (Env `FIRMA_MODE`) |
| `engine/providers/pi_provider.py` | `spawn_persistent()` statt `spawn_worker()`: kein `-p`, stdin-Pipe offen, `mode=json|rpc`, Handle zurück |
| `engine/providers/session_registry.py` | NEU: Handle-Speicher + Idle-Tracking + `stop(handle)` |
| `engine/services/message_bus.py` | NEU: `route(target, msg)`, stdout-JSONL-Subskription, Cross-Dept-Events |
| `run_pi_mesh.py` | `make_pimesh_messenger_callback`: im Collaborative-Mode Session spawnen + in Registry; Dummy-Reviewer bleibt (oder echter Reviewer als lebendige Session) |
| `engine/services/guardian.py` | Bei REVIEW_FAILURE/VERIFY_FAILURE im Collaborative-Mode: Feedback via Bus an lebendige CODER-Session routen (statt nur Re-Spawn) |
| `engine/controller.py` | `stop_run` → alle Sessions in Registry STOPpen |
| `engine/orchestrator.py` | Idle-Reaper-Task für PARKED/ALIVE Sessions |

**Invasivität:** Mittel. Kern-FSM (governance.py) unverändert. Worker-Output-Contract
(worker_response-Datei) unverändert → Receiver funktioniert weiter. Hauptsächlich neu:
Registry + Bus + spawn-Modus + Lifecycle-Hooks.

---

## 10. Offene Fragen / Risiken

1. **Idle/Parked-Timeout:** Während VERIFYING/REVIEWING darf die CODER-Session nicht vom
   Idle-Reaper gekillt werden → Timer pausieren (PARKED-State).
2. **Concurrency:** Mehrere Feedback-Runden gleichzeitig? Serialisierung über Bus nötig.
3. **Determinismus-Verlust akzeptiert?** Für Qualitäts-Runs ja; Default bleibt deterministic.
4. **Cross-Dept PLAN_REVISION:** FSM-Erweiterung nötig (siehe 4.2) — später.
5. **Ressource-Cap:** Bei vielen parallelen Tasks residente Sessions begrenzen (Pool/Semaphore).

---

## 11. Glossar

- **Session:** lebendiger `pi`-Prozess mit erhaltenem Conversation-State (system prompt + Turns).
- **Message-Bus:** Kernel-Komponente, die Feedback/Events zwischen lebendigen Sessions routet.
- **SessionRegistry:** Kernel-seitiges Verzeichnis aller lebendigen Worker-Sessions.
- **PARKED:** Session resident, aber wartet (während Verifier/Reviewer arbeiten).
- **Output-Contract:** Worker schreibt `worker_response.<task_id>.response.json` (unverändert in beiden Modi).
- **FSM:** GovernanceMatrix (PLANNING→CODING→VERIFYING→REVIEWING→COMPLETE), in beiden Modi identisch.

---

**Bottom Line für den Berater:** Collaborative Mode ist KEIN Ersatz des Kernels durch
pi-messenger, sondern die **Erweiterung des PiProvider-Substrats um persistente Agenten +
einen Kernel-Message-Bus**. Agenten „reden" über Firma, behalten Kontext, Abteilungen sind
vernetzt — bei erhaltenem State-Owner, erhaltener FSM/Audit, und ohne autonomen Mesh.
Determinismus sinkt (bewusst, qualitätsgetrieben); Token-Kosten sind bei Fix-Loops oft
niedriger. Opt-in via `FIRMA_MODE=collaborative`, Default bleibt deterministic.
