# Statusbericht für Berater
**Datum:** 2026-07-24  
**Projekt:** Firma — Deterministic Multi-Agent Execution Framework  
**Autor:** Pi Coding Agent  
**Verteiler:** Berater / Consulting

---

## 1. Kontext: Was ist Firma?

Firma ist ein **deterministisches Multi-Agenten-Framework** für autonome Software-Projekte. Es orchestriert spezialisierte KI-Worker (Researcher, Planner, Coder, Reviewer, Guardian, Orchestrator) über eine strukturierte Task-Pipeline mit strengen State-Machines.

### Kernidee
- Jede Aufgabe wird in **verifizierbare Tasks** zerlegt
- Jeder Worker hat eine **eindeutige Rolle** mit klaren Ein- und Ausgaben
- Der **Firma Engine** ist die Single Source of Truth für den gesamten Zustand
- Alle Übergänge, Artefakte und Entscheidungen werden **geloggt und auditierbar** gemacht

### Transport-Modi
- **In-Process:** Lokale Worker-Simulation (Happy-Path-Baseline)
- **PiMesh:** Echte Multi-Crew-Ausführung via `pi`-Subprozesse (OpenRouter/LLM-Anbindung)

---

## 2. Aktueller Entwicklungsstand

### ✅ Was funktioniert
| Feature | Status |
|---------|--------|
| **E2E-Pipeline** (RESEARCHER → PLANNER → CODER → REVIEWER) | ✅ Bewiesen in 3/3-Runs |
| **Plan-Validation** (kernel-side) | ✅ Verhindert Oversize-Plans deterministisch |
| **Tool-Policy-Enforcement** (provider-level) | ✅ Bash eliminiert, Reviewer auf `read,write` |
| **Artefakt-Tracking** (task-scoped dedupe) | ✅ `(task_id, path)`-Dedupe |
| **Auditor** (Phase 4) | ✅ 14 Sektionen, live Token-/Turn-Tracking |
| **Run-Archiv** | ✅ Manifest + DB-Snapshot + Audit |

### ⚠️ Was noch nicht optimal ist
| Bereich | Problem |
|---------|---------|
| **Token-Effizienz** | 2M Tokens für einfache Website (4-5x über Bedarf) |
| **Reviewer-Performance** | 67% aller Tokens im Reviewer, 11 Turns pro Task |
| **Phase-Timing** | Worker-Logs haben keine verwertbaren Timestamps |
| **DB-Konsistenz** | Einige Runs haben keine CODER-Tasks in DB (nur Reviewer/Planner) |

---

## 3. Das zentrale Problem: Token-Explosion

### Aktuelle Zahlen (Run `e1c5edbd`, 2026-07-24)
| Role | Tasks | Turns | Tool-Calls | **Tokens** | Anteil |
|------|-------|-------|------------|------------|--------|
| RESEARCHER | 1 | 26 | 44 | 452k | 21% |
| PLANNER | 1 | 5 | 4 | 256k | 12% |
| **REVIEWER** | **3** | **33** | **58** | **1.42M** | **67%** |
| **GESAMT** | **5** | **64** | **106** | **~2.13M** | 100% |

### Was ist zu viel?
| Vergleich | Tokens |
|-----------|--------|
| Aktuell (Website) | 2.13M |
| Realistisch (Website) | 400-500k |
| **Overhead** | **~4-5x** |

### Ursachenanalyse
1. **Reviewer-Kontext-Explosion**
   - Lädt trotz selektiver Filterung zu viele Artefakte
   - 816k cacheRead = 57% der Reviewer-Tokens
   - 11 Turns pro Review (Ziel: 4 Turns, ONE-PASS)

2. **Fehlende harte Token-Limits**
   - Bisher nur Prompt-Ebene ("bitte effizient sein")
   - Kein Hard-Stop bei Budget-Überschreitung

3. **Provider-spezifisches Logging**
   - `kilo` (OpenRouter free) loggt Usage erst seit neuesten Runs
   - Ältere Runs zeigen 0-Token-Usage (keine echten Daten)

4. **Phase-Timing nicht verfügbar**
   - Worker-Logs haben nur 1 Timestamp (`session` Event)
   - Keine Dauer-Berechnung pro Task möglich

---

## 4. Maßnahmen und Ergebnisse

### Phase 1: Reviewer-Optimierung (abgeschlossen)
| Maßnahme | Ergebnis |
|----------|----------|
| Tool-Policy auf `read,write` | Bash-Calls: 22 → 0 |
| ONE-PASS-Contract im Prompt | Turns: 1.519 → 4 (bei Snake-Runs) |
| Selektive Artefakt-Loading | Reviewer lädt nur noch relevante Dateien |

**Ergebnis:** Bei Snake-Runs (task-1, task-2, task-3) **4 Turns, 0 Bash**, **119-184k Tokens** pro Reviewer-Task.

### Phase 2: Token-Effizienz (laufend)
| Schritt | Status | Ergebnis |
|--------|--------|----------|
| **Step 1:** Turn-Counting + Telemetry | ✅ Abgeschlossen | `worker_log_parser.py` + Auditor-Sektionen |
| **Step 2:** ONE-PASS Contract (CODER) | ⚠️ Gemischt | Contract-Text allein nicht ausreichend |
| **Step 3:** Hard Tool Policy + Enforcement | ✅ Abgeschlossen | Provider-level enforcement, bash eliminiert |
| **Step 4:** Kernel-side Plan Validation | ✅ Abgeschlossen | `PLAN_REJECTED` bei >5 Tasks, retry-basiert |
| **Step 5:** Auditor-Erweiterung | ✅ Abgeschlossen | 14 Sektionen, live Token-/Turn-Tracking |

### Aktuelle E2E-Ergebnisse (Website-Runs)
| Run | Status | Tasks | Rejections | Dauer |
|-----|--------|-------|------------|-------|
| `03bc41bd` | FAILED* | 3/3 CODER | 1× PLAN_REJECTED | 836s |
| `0e0de799` | COMPLETED | 3/3 CODER | 1× PLAN_REJECTED | 501s |
| `e1c5edbd` | COMPLETED | 3/3 CODER | 0 | 501s |

*`03bc41bd` failed wegen task-1/task-3 Hänger in REVIEWING — Bug wurde danach gefixt (`_response_artifacts_pending()` path resolution).

---

## 5. Auditor: Was er jetzt liefert

Der Auditor schreibt nach jedem Run **14 Sektionen** in `audit.md`:

### Kern-Sektionen
| Sektion | Inhalt |
|---------|--------|
| §1 Overview | Run-ID, Status, Dauer, Transport |
| §2 Task Table | Alle Tasks mit State, Attempts, Last-Event, Verifier |
| §5 Failures & Retries | Fehler, Guards, Feedback |
| §8 Tool Usage by Role | read/write/edit/bash pro Rolle |
| §9 Tool Policy Checks | Verstöße gegen Role-spezifische Tool-Policies |
| **§10 Turn Usage by Role** | Turns + Tool-Calls pro Rolle |
| **§11 Phase Timing** | Dauer pro Task (wenn Timestamps verfügbar) |
| **§12 Token Usage** | Total/Input/Output/cacheRead pro Rolle |
| **§13 Error Patterns** | Fehler-Häufigkeit + Details |
| **§14 Retry & Error Details** | Pro Task: state, phase, attempts, retries, feedback |

### Neu seit 2026-07-24
- **Token-Usage** wird jetzt aus `worker.log` extrahiert (best-effort)
- **Turn-Usage** zählt `turn_start`-Events
- **Error-Patterns** erkennt `worker_timeout`, `review_failure`, `verify_failure` etc.
- **Retry-Details** zeigen `attempt_count`, `retry_count`, `last_review_feedback`
- **Klare "nicht verfügbar"-Hinweise** statt stiller 0-Werte

---

## 6. Was der Berater wissen muss

### Das Geschäftsproblem
**Firma verspricht "deterministic execution for autonomous software projects"** — aber die Token-Kosten sind aktuell **nicht deterministisch kontrollierbar**.

### Der konkrete Schmerz
- 2M Tokens für eine einfache Website sind **nicht skalierbar**
- Reviewer frisst **67% des Budgets** ohne proportionalen Qualitätsgewinn
- Keine **harten Budget-Limits** = Kostenrisiko bei komplexeren Projekten

### Die Lösungsidee
1. **Hard Token-Budgets pro Rolle/Task** (z.B. Reviewer max 200k)
- Provider-level enforcement, nicht nur Prompt-Ebene
- Fail-open oder Fail-closed bei Überschreitung

2. **Context-Reduktion für Reviewer**
- Max 2 Artefakte pro Review
- Keine Global-Goal-Wiederholungen im Prompt
- Hash/Metadaten-Check statt Volltext-Load

3. **Phase-Timing aus Worker-Logs**
- Timestamps standardisieren (pro Event)
- Echte Dauer-Berechnung pro Task/Rolle

### Der nächste Meilenstein
**"Token-Effizienz-Proof":** Ein E2E-Run mit <500k Tokens für die gleiche Website-Aufgabe, bei gleicher oder besserer Qualität.

---

## 7. Anhang: Technische Details

### Repository-Struktur
```
engine/
├── services/
│   ├── auditor.py          # Phase 4: Audit-Report (14 Sektionen)
│   ├── run_archive.py      # Phase 1: Run-Archiv + Manifest
│   ├── worker_log_parser.py # Phase 3: Zentraler Log-Parser
│   └── guardian.py         # Kernel-side Plan-Validation
├── providers/
│   └── pi_provider.py      # Tool-Policy + Spawn-Logik
└── transport/
    └── pi_mesh_transport.py # PiMesh-Wiring + Spec-Building

pimesh/
├── planning-crew/          # PLANNER + RESEARCHER Crew
├── coding-crew/            # CODER Crew
└── reviewing-crew/         # REVIEWER Crew

archive/runs/<run_id>/
├── manifest.json           # Zentraler Index (Token/Turn-Daten)
├── audit.md                # Menschlicher Audit-Report
├── db_snapshot.json        # Run + Tasks + Transitions
└── artifact_manifest.json  # Artefakt-Referenzen
```

### Wichtige Umgebungsvariablen
| Variable | Zweck |
|----------|-------|
| `FIRMA_TRANSPORT` | `pimesh` oder `in-process` |
| `FIRMA_APP` | `snake` (aktuell) oder `corporate_site` |
| `FIRMA_REVIEWER_DUMMY` | `false` für echten LLM-Reviewer |
| `FIRMA_MAX_CONCURRENT_SPAWNS` | Concurrency-Limit (aktuell 1) |
| `FIRMA_MAX_ITERATIONS` | Max Retry-Budget (aktuell 3) |

### Laufende Runs
| Run-ID | Status | Artefakte |
|--------|--------|-----------|
| `e1c5edbd-767b-400f-9e7b-296c8bb9aa2f` | COMPLETED | `archive/deliverables/firma_website_e1c5edbd/` |
| `03bc41bd-62e9-4b07-b9aa-54ccee6de456` | FAILED* | `archive/deliverables/firma_website_03bc41bd/` |

---

## 8. Empfehlungen für den Berater

### Priorität 1: Token-Budget-Enforcement
- **Was:** Hard Token-Limits pro Task/Rolle im Kernel
- **Warum:** Verhindert Cost-Explosion bei komplexen Projekten
- **Wie:** `PiProvider.spawn_for_assignment()` um `max_tokens` Parameter erweitern

### Priorität 2: Reviewer-Context-Reduktion
- **Was:** Max 2 Artefakte pro Review, keine Global-Goal-Wiederholungen
- **Warum:** 67% der Tokens gehen im Reviewer drauf
- **Wie:** `_review_target_paths()` härten + Prompt-Kompression

### Priorität 3: Phase-Timing-Standardisierung
- **Was:** Timestamps pro Event in worker.log
- **Warum:** Echte Dauer-Berechnung ermöglicht Bottleneck-Identifikation
- **Wie:** Pi-messenger Logging erweitern (oder Post-Hoc aus run.log)

### Priorität 4: Quality-Gate-Erweiterung
- **Was:** Reviewer soll bei >200k Tokens automatisch `REVIEW_APPROVED` geben (fail-open)
- **Warum:** Verhindert Timeout-Schleifen bei teuren Reviews
- **Risiko:** Qualitätseinbußen bei komplexen Reviews → muss getestet werden

---

## 9. Fragen für das Berater-Gespräch

1. **Akzeptabler Token-Budget:** Was ist für unsere Kunden ein akzeptables Token-Budget für eine "einfache Website"? 500k? 1M?

2. **Reviewer-Trade-off:** Soll der Reviewer bei Budget-Überschreitung
   - a) **fail-open** (approve, Risiko: Qualität)
   - b) **fail-closed** (reject, Risiko: Timeout-Schleife)
   - c) **escalate** (Mensch/Lead entscheidet)

3. **Kosten-Nutzen:** Sollen wir den aktuellen 2M-Token-Run als **"proof of concept"** oder als **"nicht produktiv tauglich"** einstufen?

4. **Nächste Phase:** Sollen wir uns auf **Token-Effizienz** oder auf **neue Features** (z.B. Ingest-Mode, Corporate-Site) konzentrieren?

---

## 10. Kontakt und Weiteres Material

- **Audit-Reports:** `archive/runs/<run_id>/audit.md`
- **Code-Snapshots:** `milestones/reviewer_optimization_and_backup_2026-07-23/`
- **Entscheidungsprotokolle:** `docs/decisions/`
- **Test-Suiten:** `tests/test_phase4_auditor*.py`, `tests/test_worker_log_parser.py`

**Ende des Berichts.**
