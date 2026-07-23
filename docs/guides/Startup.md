# Firma starten — Anleitung & Übersicht

**Wichtig vorab:** Firma hat keinen „Knopf" / keine GUI. Der Start erfolgt über die
Kommandozeile — in der Praxis meist durch den Agenten (pi), der das entsprechende
`python run_snake.py …` Kommando absetzt. Dieses Dokument fasst zusammen, was dabei
wichtig ist, welche Umgebungs-Variablen (ENV) den Lauf steuern und wo die Ergebnisse
landen.

---

## 1. Voraussetzungen (müssen erfüllt sein)

| Komponente | Ort / Befehl | Prüfung |
|---|---|---|
| Python (3.14) | `C:/Users/arthu/AppData/Local/Python/bin/python3` | `python3 --version` |
| `pi` CLI | `C:/Users/arthu/AppData/Roaming/npm/pi` (v0.79.x) | `pi --version` |
| pi-messenger Extension | `~/.pi/agent/npm/node_modules/pi-messenger` | Verzeichnis vorhanden? |
| Crew-Verzeichnisse | `pimesh/planning-crew`, `pimesh/coding-crew`, `pimesh/reviewing-crew` (je mit `.pi/messenger/crew/`) | vorhanden? |
| Arbeitsverzeichnis | `C:/Users/arthu/Coding/Firma` | hier wird gestartet |

> Nur im **PiMesh-Modus** (`FIRMA_TRANSPORT=pimesh`) werden `pi`-Subprozesse
> (Planner/Coder/Reviewer) tatsächlich als externe Worker gestartet. Im
> **in-process**-Modus läuft alles im selben Python-Prozess (Simulation).

---

## 2. Die zwei Einstiegspunkte

### A. `run_snake.py`  ← **Haupt-Einstieg** (alle 5.x-Läufe)
Wählt Transport + App über ENV, baut die DB, startet den Orchestrator und wartet
bis der Run terminal ist.

```bash
FIRMA_TRANSPORT=pimesh FIRMA_APP=snake FIRMA_REVIEWER_DUMMY=false \
  python run_snake.py
```

### B. `run_pi_mesh.py`  ← **nur Hilfs-Modul / Transport-Isolation** (sekundär)
Stellt `PiMeshReceiverLoop` + `make_pimesh_messenger_callback` bereit, aber sein
eigenes `main_logic` macht **nur `transport.dispatch` (Task-Datei schreiben) — es
startet KEINE `pi`-Worker**. Worker werden NUR gespawned, wenn
(a) du `run_snake.py` nutzt (das verdrahtet den `PiProvider`-Spawn-Callback), oder
(b) ein separater pi-messenger-swarm-Harness die Crew-Verzeichnisse beobachtet.

> ⚠️ **Häufiger Fehler:** `python run_pi_mesh.py` allein starten → Tasks werden
> zwar dispatchedd, aber **ES LÄUFT KEIN WORKER** → Tasks laufen in `WORKER_TIMEOUT`
> bzw. „responding slowly", der Run terminiert nie sauber. **Für echte Läufe immer
> `run_snake.py` nutzen** (siehe §2.A).

```bash
# Achtung: startet KEINEN Worker — nur für Transport-Isolation mit externem Harness
FIRMA_TRANSPORT=pimesh python run_pi_mesh.py
```

---

## 3. ENV-Switches (das Wichtigste zum Steuern eines Laufs)

| Variable | Default | Werte | Wirkung |
|---|---|---|---|
| `FIRMA_TRANSPORT` | `in-process` | `in-process` \| `pimesh` | **Modus**: Simulation im selben Prozess vs. echte `pi`-Subprozesse über PiMesh. |
| `FIRMA_APP` | `snake` | `snake` \| `counter` | Welche App gebaut wird (Snake-Spiel bzw. 3-Datei-Counter-App). |
| `FIRMA_REVIEWER_DUMMY` | `false` | `true` \| `false` | **`false`** = echter LLM-Reviewer (sieht den Code, wirklich Review). **`true`** = Reviewer-Bypass (sofort `REVIEW_APPROVED`, kein LLM). _Default seit 16.07.: echt._ |
| `FIRMA_SESSION_MODE` | `off` | `off` \| `task` \| `persona_base` | **`off`** = heute (deterministic, `--no-session`). `task` = Retry-Continuity (Dev-Empfehlung für pimesh). `persona_base` = Warm-Base copy-on-start (6.3.a, implementiert + E2E bewiesen). Benötigt eine geseedete Base unter `data/sessions/_base/<dept>/<persona>/<role>/` (sonst fail-safe auf task-mode). |
| `FIRMA_PERSONA_ID` | `default` | beliebige ID | Welche Persona die Warm-Base seeded (nur bei `SESSION_MODE=persona_base`). Department wird aus der Rolle abgeleitet (PLANNER→planning, CODER→coding, REVIEWER→reviewing). Base erzeugen/verifizieren: `tools/seed_base_session.py` (siehe `docs/Seeding.md`). |
| `FIRMA_MAX_CONCURRENT_SPAWNS` | `2` | Zahl ≥1 | **P1:** begrenzt gleichzeitige pimesh-`pi`-Spawns (Free-Tier Rate-Limit-Schutz). `1` = voll serialisiert (Dev-Empfehlung bei Free-Tier). |
| `FIRMA_SEED_TIMEOUT` | `340` | Zahl (s) | **P2:** Hartes Timeout pro Seed/Verify-`pi`-Spawn, damit das Script nicht haengt. |
| `FIRMA_PROCESS_MODE` | `oneshot` | `oneshot` \| `resident` | **`oneshot`** = fire-and-forget. `resident` = Live-Prozess (6.3.b, deferred, Risiko). |
| `FIRMA_MAX_SESSION_DISK_MB_PER_RUN` | `200` | Zahl (MB) | Disk-Cap pro Run; bei Überschreitung spawn fail-safe **ohne** Session. `0` = aus. |
| `FIRMA_MODEL_PLANNER` | *(unset)* | `provider/modell` | Optional: erzwingt Modell für PLANNER. **Wenn unset → `pi` nutzt seinen eigenen Default** (beim User: `kilo/kilo-auto/free`). |
| `FIRMA_MODEL_CODER` | *(unset)* | `provider/modell` | Optional: erzwingt Modell für CODER. Ansonsten pi-Default. |
| `FIRMA_MODEL_REVIEWER` | *(unset)* | `provider/modell` | Optional: erzwingt Modell für REVIEWER. Ansonsten pi-Default. |
| `FIRMA_MODE` | — | `deterministic` \| `collaborative` | **Geplant (noch nicht implementiert)** für Collaborative Mode (Phase 6.x). Aktuell immer deterministic. |

> **Modell-Regel (PiProvider = Compute-Substrat):** PiProvider erzwingt KEIN Modell.
> Nur wenn `FIRMA_MODEL_*` gesetzt ist, wird `--provider/--model` an den `pi`-Subprozess
> durchgereicht. Sonst nutzt `pi` seinen eigenen Default. Das vermeidet das
> Überschreiben mit einem zu langsamen/schwachen Modell (Ursache der 5.2-Timeouts).
>
> ⚠️ **Free-Modell-Pitfall (wichtig!):** Ein EINZELNES kostenloses Modell
> (z.B. `kilo/kwaipilot/kat-coder-pro-v2.5:free`) hat eine **winzige Quota** → sofort
> `429 您的请求频率过高` (Rate-Limit), sobald mehrere Tasks/Retries feuern. Der
> Auto-Router `kilo-auto/free` (pi-Default) vermeidet das, indem er Last über mehrere
> Modelle verteilt — er ist langsamer/variabler, aber **zuverlässig**. **Empfehlung:
> `FIRMA_MODEL_*` ungesetzt lassen → Auto-Router.**

---

## 4. Typische Start-Kommandos

### Snake mit echtem Reviewer (PiMesh, pi-Default-Modell)
```bash
FIRMA_TRANSPORT=pimesh FIRMA_APP=snake FIRMA_REVIEWER_DUMMY=false \
  nohup python run_snake.py > archive/logs/phase5_snake_$(date +%s).log 2>&1 &
```

### Counter-App (PiMesh, dummy Reviewer)
```bash
FIRMA_TRANSPORT=pimesh FIRMA_APP=counter FIRMA_REVIEWER_DUMMY=true \
  python run_snake.py
```

### Snake mit Dummy-Reviewer + Reject-Once (Phase 6.2 Validierung, Auto-Router)
```bash
FIRMA_TRANSPORT=pimesh FIRMA_REVIEWER_DUMMY=true FIRMA_REVIEWER_DUMMY_REJECT_ONCE=true \
  nohup python run_snake.py > archive/logs/phase6_2_$(date +%s).log 2>&1 &
```
> Bewährt: Run `99b9f0e6-…` lief in **~5 Min COMPLETED** durch (alle 3 Tasks
> `REVIEW_APPROVED`, inkl. task-2 Dummy-Reject→Retry→Approve, d.h. der 6.2-Loop
> ist bewiesen). Artefakte in `data/artifacts/<RUN_ID>/task-{1,2,3}/`
> (`index.html` / `style.css` / `game.js`). Kein `FIRMA_MODEL_*` gesetzt → Auto-Router.

### Dev: Session-Continuity (Stufe 2, `SESSION_MODE=task`)
```bash
FIRMA_TRANSPORT=pimesh FIRMA_SESSION_MODE=task \
  nohup python run_snake.py > archive/logs/phase6_2_task_$(date +%s).log 2>&1 &
```
> **Lokal/Dev:** Retry-Continuity — ein CODER-Retry lädt dieselbe Session-ID und sieht
> den ersten (gescheiterten) Versuch. Code-Default bleibt `off` (bestehende Runs unverändert).
> Observability: jeder Spawn-Log zeigt `session_mode=task, session_id=...`.
> Disk-Guard: bei `> FIRMA_MAX_SESSION_DISK_MB_PER_RUN` spawn fail-safe ohne Session.

### Schnell-Check im in-process-Modus (kein `pi`-Subprozess)
```bash
FIRMA_TRANSPORT=in-process FIRMA_APP=snake FIRMA_REVIEWER_DUMMY=true \
  python run_snake.py
```

---

## 5. Was beim Start passiert (Ablauf)

1. **DB anlegen**: `data/db/snake_run_<PID>.db` (pro Lauf eine eigene DB →
   vermeidet Windows-SQLite-Locks). Bei `run_pi_mesh.py`: `data/db/snake_pimesh.db`.
2. **Transport wählen**:
   - `pimesh` → `PiMeshTransport` + `PiProvider` (spawnt `pi`-Worker) + `PiMeshReceiverLoop`
     (pollt die `worker_response.*.response.json`).
   - `in-process` → `InternalTransport` + `WorkerSim` (alles im Prozess).
3. **`controller.start_run(run_id)`** → startet den **Orchestrator** (`run_forever`,
   Tick alle 0,5 s): liest Messages, Guardian-Intake, FSM-Transitions, Verifier,
   Scheduler-Spawns.
4. **Hauptschleife** (`run_snake.py`): pollt `get_run_status` alle 5 s.
   Bei Status `COMPLETED` / `FAILED` / `CANCELLED` → Loop-Ende → `stop_run`.
5. **Cleanup**: `stop_run` beendet Orchestrator + Receiver, räumt auf. Der
   **Run-Status wird dabei NICHT überschrieben** (er wurde bereits korrekt von
   `_check_run_completion` bzw. Guardian gesetzt).

---

## 6. Wo landen die Ergebnisse?

| Artefakt | Pfad |
|---|---|
| **Run-DB** (Tasks, FSM, Messages) | `data/db/snake_run_<PID>.db` |
| **Task-Artefakte** (index.html, game.js, …) | `data/artifacts/<RUN_ID>/<TASK_ID>/` |
| **Receiver-Log** (einzelne Worker) | `pimesh/*-crew/.pi/worker.log` |
| **Worker-Responses** (Completion-Signal) | `pimesh/*-crew/.pi/messenger/crew/worker_response.<task>.response.json` |
| **Lauf-Log** (wenn von Agent umgeleitet) | `archive/logs/phase5_snakeN_<epoch>.log` |
| **Deliverable** (zusammengebaut) | `deliverables/snake_game_5_2/` (manuell aus Artefakten kopiert) |

---

## 7. Wie ein Run endet (Governance)

- Ein Run erreicht einen **Terminal-State** erst wenn **ALLE Tasks** einen
  Terminal-State haben (`COMPLETE` / `FAILED` / `FAILED_ITERATION_LIMIT`).
- Finaler Run-Status (in `engine/orchestrator.py::_check_run_completion`):
  - alle Tasks `COMPLETE` → **`COMPLETED`**
  - mind. ein Task `FAILED` → **`FAILED`** (mit `failure_reason` = fehlgeschlagene Task-IDs)
- **Fail-Fast-Prinzip:** Scheitert eine Task, wird der Run nicht sofort, sondern
  erst nach Abarbeiten aller (noch laufenden) Tasks als `FAILED` markiert — so
  wird kein noch aktiver Reviewer/Worker abgebrochen.
- `stop_run` überschreibt den Status **nie** (Bug-fix: zuvor stand hier hart
  `COMPLETED` → ein fehlgeschlagener Run wurde fälschlich als Erfolg gemeldet).

---

## 8. Wichtige Dateien (Faden zum Ziehen bei Fragen)

- `run_snake.py` — Haupt-Einstieg, Modus/App-Auswahl, Hauptschleife.
- `engine/controller.py` — Run-Lifecycle (start/stop), **Status-Erhalt** in `stop_run`.
- `engine/orchestrator.py` — Tick-Loop, **`_check_run_completion`** (Run-Status).
- `engine/services/guardian.py` — Governance/FSM-Intake, Invarianten, Retry.
- `engine/transport/pi_mesh_transport.py` — PiMeshTransport (Spec + Artifact-Handoff).
- `run_pi_mesh.py` — `PiMeshReceiverLoop` (pollt Responses), `make_pimesh_messenger_callback`.
- `engine/providers/pi_provider.py` — `PiProvider` (spawnt `pi`-Subprozesse, Modell optional).
- `engine/settings.py` — ENV-Defaults (`FIRMA_*`, `PIMESH_MODELS`).

---

## 9. Troubleshooting (Windows-spezifisch)

- **Prozess hängt / muss gekillt werden:**
  `taskkill //F //IM python3.exe` (Windows tree-kill; kein `SIGKILL`).
- **Alte `pi`-Worker aufräumen:** nach Command-Line-Match auf den Crew-cwd scannen
  (gleiche Verzeichnisse wie oben) und beenden.
- **SQLite-Lock:** pro Lauf eigene `snake_run_<PID>.db` (nicht eine globale DB).
- **Worker-Response ungültig (double-escaped JSON):** Receiver (`run_pi_mesh.py`)
  repariert doppelt-escaped JSON automatisch (`_try_unescape_json`).
- **Run meldet `COMPLETED`, obwohl Task failed:** sollte nach dem Fix in §7 nicht
  mehr vorkommen — dann `stop_run` prüfen.

---

## 10. Checkliste für einen sauberen Start

- [ ] Im richtigen Verzeichnis (`C:/Users/arthu/Coding/Firma`)?
- [ ] `python3`, `pi`, pi-messenger-Extension vorhanden?
- [ ] `pimesh/*-crew/.pi/messenger/crew/` vorhanden?
- [ ] `FIRMA_TRANSPORT` gesetzt (`pimesh` für echte Worker)?
- [ ] `FIRMA_REVIEWER_DUMMY` bewusst gewählt (meist `false` für echten Review)?
- [ ] Kein `FIRMA_MODEL_*` nötig → pi-Default (Auto-Router) wird genutzt (empfohlen).
- [ ] Log-Datei umgeleitet (`> archive/logs/...log 2>&1 &`)?
- [ ] Alte `pimesh/*-crew/.pi/...` Artefakte/Responses vorher ggf. bereinigt?

---

## 11. Wichtigste Fallstricke (aus der Praxis)

1. **Falscher Einstieg (`run_pi_mesh.py` statt `run_snake.py`)** — siehe §2.B.
   Symptom: Tasks werden dispatchedd, aber kein Worker läuft → ewige
   „responding slowly" / Timeouts. **Fix: `python run_snake.py`.**
2. **Free-Modell pinnen → `429` Rate-Limit** — ein einzelnes kostenloses Modell
   ist ratelimitiert; der Auto-Router (`kilo-auto/free`, pi-Default) verteilt die
   Last und bleibt zuverlässig. **Fix: `FIRMA_MODEL_*` leer lassen.**
3. **Import-Bug auf Branch `chore/clean-architecture`** — `DatabaseManager` liegt
   in `engine/db.py` (nicht mehr `engine.repository`). `run_snake.py` ist bereits
   korrekt; `run_pi_mesh.py` importierte falsch und crashte — **bereits gefixt**
   (`from engine.db import DatabaseManager`).
4. **Artefakte sind pro Task verteilt** — die Snake-App entsteht über 3 Tasks
   (task-1→`index.html`, task-2→`style.css`, task-3→`game.js`). Für ein spielbares
   Verzeichnis die drei Dateien zusammenkopieren (z.B. `deliverables/snake_game_6_2/`).
5. **Prozess-Kill unter Windows** — der von `nohup … &` gemeldete Bash-PID ist ein
   Shim; der echte Windows-PID steht in `tasklist` (Spalte PID). Killen via
   `powershell -Command "Stop-Process -Id <WIN_PID> -Force"` — nicht via den
   Bash-Shim-PID (der greift ins Leere, Prozess hält DB-Lock).
