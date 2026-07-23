# Plan — Phase 4: Auditor (Idee C)

- **Datum:** 2026-07-16
- **Branch:** `chore/clean-architecture`
- **Status:** Draft / NOT IMPLEMENTED
- **Vorgänger:** Phase 1 (RunArchiver, Idee D), Phase 2 (Ordner-Ingest + Coder-Edit, Idee A), Phase 3 (Researcher, Idee B)
- **Entscheidung:** V1 = **deterministisch, LLM-frei** (reine Aggregation + Bericht). Begründung unten.

---

## 1. Sinn / Grund

Inzwischen gibt es viele bewegliche Teile (Sessions, persona_base, Ingest/Baseline, Scope-Verifier,
Research-Brief, Run-Archive). Debugging und Iteration kosten Zeit, weil die Erkenntnisse über mehrere
Dateien/DB-Tabellen verstreut sind. Ein **read-only Auditor**, der nach Run-Terminal alles strukturiert
zusammenfasst, senkt die Debug-Zeit — **ohne die Kernlogik zu riskieren** (keine neuen Transitions,
kein Eingriff in Run-State, keine Retries). Die Datenquellen existieren bereits; es ist primär
Aggregation + Bericht.

---

## 2. Umfang (V1 — low-risk, read-only)

Der Auditor:
- läuft **nach Run-Terminal** (COMPLETED oder FAILED).
- ist **strikt read-only**: liest Archiv-Manifest + DB, schreibt NUR Bericht.
- schreibt genau zwei Dateien in `archive/runs/<run_id>/`:
  - `audit.md` (menschlich lesbar, narrative Struktur)
  - `audit.json` (maschinenlesbar, 1:1 die gleichen Felder)
- **kein** LLM, **keine** „Executive Summary", **kein** Halluzinieren. Harte Zahlen + Links/Querverweise.

Nicht in V1: pi-usage-Kosten (noch nicht strukturiert vorhanden) → im Audit als **„known unknown"**
markieren, nicht erfinden.

---

## 3. Datenquellen (konkret, bereits vorhanden)

| Quelle | Feld/Inhalt | Verwendung im Audit |
|---|---|---|
| `archive/runs/<run_id>/manifest.json` | run_id, app, transport, started_at, terminal_state, task_summary, config_snapshot, baseline_manifest, workspace_root, scope_summary, research_brief, artifact_refs | Overview, Scope, Artifacts, Repro |
| `archive/runs/<run_id>/db_snapshot.json` | terminal_state, task_summary, failure_reason, summary_counters | Overview, Failures |
| DB `Task` (via `controller`) | assigned_role, state, execution_phase, attempt_count, retry_count, verification_type, dependencies, expected_artifacts, last_review_feedback, assigned_worker, events | Task Table |
| DB `TaskTransitionLog` | event (VERIFY_FAILURE/TASK_FAILED/WORKER_TIMEOUT/…), from/to_phase, sender_role | „welche Guards ausgelöst" |
| `archive/runs/<run_id>/research_brief.md` | Researcher-Briefing | Research Summary (Link + erste Zeilen) |
| `archive/runs/<run_id>/baseline_manifest.json` | Projekt-File-Hashes | Scope/Drift (File-Anzahl, geändert) |
| `archive/runs/<run_id>/run.log` | optionaler Log-Capture | optionaler Verweis |

Der Auditor liest **ausschließlich**; er schreibt nur `audit.md`/`audit.json`.

---

## 4. Output-Schema (`audit.md` Struktur)

```
# Run Audit: <run_id>

## 1. Run Overview
- run_id, app, transport, terminal_state, started_at, duration
- persona_id / session_mode (aus config_snapshot, falls vorhanden)

## 2. Task Table
| task_id | role | terminal_state | attempts | last_event | verifier |
(...eine Zeile pro Task...)

## 3. Scope / Drift Summary
- Ingest-Modus: ja/nein (baseline_manifest vorhanden?)
- scope_summary je Task: changed / new / removed + Violation-Code (falls vorhanden)
- baseline: N Files erfasst

## 4. Research Summary
- research_brief vorhanden? Link. Erste Zeilen des Briefs.
- sonst: „no research phase"

## 5. Failures & Retries
- run.failure_reason (falls gesetzt)
- je fehlgeschlagener Task: state, execution_phase, letzter Transition-Event, inferierter Guard
- retry/attempt counts

## 6. Artifacts / Deliverable pointers
- artifact_refs (count), deliverables/ falls vorhanden

## 7. Repro Commands
- ENV-Snapshot aus config_snapshot (FIRMA_* Werte)
```

`audit.json` = dict mit denselben Sektionen (maschinenlesbar).

**Guard-Inferenz (deterministisch, V1):**
- Task FAILED + `execution_phase == RESEARCHING` → `research_readonly_guard` (Drift im project/-Subtree).
- Task FAILED + hat `scope_summary`-Eintrag mit Violation-Code (`PROTECTED_VIOLATION`/`SCOPE_VIOLATION`/`UNEXPECTED_NEW_FILE`) → `scope_guard`.
- Letzter `TaskTransitionLog.event == WORKER_TIMEOUT` → `worker_timeout_guard`.
- Letzter Transition-Event `VERIFY_FAILURE` → `verifier_guard` (Typ aus `verification_type`).
- Sonst: `governance_guard` + Verweis auf Transition-Log.
- Kein Treffer → `"unknown (see transition log)"` — **nie** erfinden.

---

## 5. Integrationspunkt

**Empfehlung (1): in `RunArchiver.archive_run()` am Ende.**
- Das Archiv ist Single Source; der Auditor hängt sich exakt dort an, wo das Archiv entsteht.
- Best-effort (non-fatal wie der Rest des Archivers): falls der Audit misslingt, darf der Run
  nicht blockiert werden.

Skizze (in `archive_run`, nach `_write_json(db_snapshot.json, …)`):
```python
try:
    from engine.services.auditor import RunAuditor
    await RunAuditor().write_report(run_id, run_dir, controller)
except Exception as exc:
    logger.warning(f"[Archiver] auditor report failed (non-fatal): {exc}")
```

---

## 6. Tests (damit „Proven")

- **Unit 1** `test_auditor_generates_markdown_from_manifest_and_db_stub()`:
  Seed einer DB (Run + Tasks mit gemischten States + Transition-Logs), schreibe
  `manifest.json`+`db_snapshot.json` in ein `run_dir`, rufe `RunAuditor().write_report(...)`,
  assert: `audit.md` existiert, enthält run_id, alle 7 Sektionen, korrekte Task-Anzahl im Task Table.
- **Unit 2** `test_auditor_handles_missing_optional_fields_gracefully()`:
  `write_report` mit minimalem Manifest (nur run_id), keine DB-Tasks, keine optionalen Dateien
  → erzeugt `audit.md` OHNE Crash; fehlende Sektionen als „n/a".
- **Light Integration** `test_auditor_runs_after_archive()`:
  Seed Run + Tasks in echter DB, rufe `RunArchiver.archive_run(...)` (Integration wie Phase 1/2/3),
  assert: `audit.md` liegt im Archiv und enthält run_id + terminal_state + Tasks-Count.

---

## 7. Implementierungs-Schritte (Staged, wie etabliert)

1. **Step4.1 — Auditor-Modul + Unit-Tests**
   - `engine/services/auditor.py`: `class RunAuditor` mit `async write_report(run_id, run_dir, controller)`.
   - Liest Manifest + DB (Tasks, TransitionLogs) + optionale `research_brief.md`/`baseline_manifest.json`/`run.log`.
   - Baut `audit.md` + `audit.json`, schreibt beide nach `run_dir`.
   - `tests/test_phase4_auditor.py`: Unit 1 + Unit 2 (gegen DB-Stub + Manifest-Stub).
   - Commit (nur Modul + Unit-Tests).
2. **Step4.2 — Archiv-Hook + Light Integration**
   - `engine/services/run_archive.py`: Hook in `archive_run()` (non-fatal).
   - `tests/test_phase4_auditor_integration.py`: Light Integration (Seed + `archive_run` + assert `audit.md`).
   - Commit.
3. **E2E-Proof + Tag**
   - Regression aller Phasen (Phase 1/2/3 + Phase 4).
   - `audit.md` erscheint nach einem Terminal-Run im Archiv (über bestehende E2E-Harnesse
     `e2e_phase2`/`e2e_phase3` mitarchiviert prüfbar).
   - Commit + Tag `phase4-e2e-auditor-proven`.

---

## 8. Akzeptanz

- Nach jedem archivierten Run liegt `archive/runs/<run_id>/audit.md` (+ `audit.json`) vor.
- Enthält run_id, terminal_state, Task-Table mit allen Tasks, Scope/Drift-Zusammenfassung,
  Research-Link (falls vorhanden), Failures+Guards (falls vorhanden), Artifact-Pointer, Repro-ENV.
- Fehlende optionale Felder führen nie zu Crash (graceful).
- Kein LLM-Aufruf, keine Seiteneffekte außer den zwei Audit-Dateien.

---

## 9. Risiken / Hürden

- **Hook muss non-fatal sein** (Archiv darf Run nicht blockieren) — wie bestehender Archiver-Code.
- **Guard-Inferenz ist Heuristik** — bei unklaren Fällen explizit „unknown (see transition log)",
  niemals Halluzination.
- **DB-Lese im Auditor**: read-only über `controller.db.session_scope()`; keine Writes.
- **Lange Run.logs**: nur Verweis/Link, nicht voll einbetten (V1).

---

*Dieser Plan ist ein Draft. Implementierung erst nach Freigabe (Unit → E2E → commit+tag).*
