# Plan: Phase 1 — Run-Archivierung (Idee D)

**Baseline / Referenz:** `docs/Vision_Inkrementell_Researcher_Auditor.md` (commit `48924704`,
Status: Draft / not implemented), dort §5 (Idee D) + §9 H5 + §11 Q6 (Archiv-Retention).
**Branch:** `chore/clean-architecture`
**Ziel:** Jeder Run wird nach Erreichen eines Terminal-States archiviert (Metadaten + Logs +
Artefakt-Links). Ohne den laufenden Cleanup zu gefährden, ohne „alles doppelt" zu speichern.
**Risiko:** Niedrig — ein neues Modul `run_archive.py`, ein Hook an 3 *bereits existierenden*
Terminal-Stellen, Settings-Erweiterung. **Keine Kernel-Änderung.**

---

## 1. Sinn und Grund (warum gerade jetzt)

- **Lernen / Audit / Regression / Backtrack:** ein erhaltenes Run ist die einzige ehrliche
  Antwort auf „was lief wann schief, welcher Ablauf". Ohne Archiv raten wir.
- **Billig:** die Daten (Run-DB, Artefakte, Logs) existieren größtenteils schon — es ist Plumbing,
  kein neues Modell.
- **Auditor-Voraussetzung (Review-Empfehlung):** Archiv **vor** Auditor. Sonst ist der spätere
  Auditor-Bericht nicht nachvollziehbar. Phase 1 schafft genau diese Basis.

---

## 2. Leitentscheidung (Scope)

- Archiviert wird **nur**: Run-Metadaten + Logs + Deliverables-**Links** (Manifest/Pointer).
- Artefakte werden **nicht dupliziert** — das Archiv referenziert `data/artifacts/<run_id>/...`.
- Optional (default aus): komprimiertes `data/artifacts/<run_id>` für „self-contained".

---

## 3. Was landet im Archiv (`archive/runs/<run_id>/`)

| Datei | Inhalt | Quelle |
|---|---|---|
| `manifest.json` | zentraler Index (siehe §6) | RunArchiver |
| `config_snapshot.json` | `FIRMA_*`-Settings + relevante `os.environ` zum Run-Start | `engine/settings.py` + `os.environ` |
| `db_snapshot.json` | Run-DB-Export (**schlank**, v1): Run-Record + Task-States + `failure_reason` + Summary-Counters | `controller.get_run_summary` |
| `artifact_manifest.json` | Liste der Artefakte unter `data/artifacts/<run_id>/` (rel. Pfade + bytes) | ArtifactStore-Walk |
| `run.log` | Run-spezifische Log-Zeilen (narrator/transition + Plattform) | FileHandler (§5) |

---

## 4. H5 (Cleanup vs Retention) — festgenagelt

- **Cleanup bleibt in place:** bestehender Launch-Cleanup entfernt Run-Session-Dirs (außer `_base`)
  wie bisher. Das Archiv wird davon **nicht** berührt.
- **Archiv = separater Baum:** `archive/runs/<run_id>/` (unter `ARCHIVE_DIR`), nie vom Cleanup gelöscht.
- **Retention `KEEP_LAST_N`** (ENV `FIRMA_ARCHIVE_KEEP_LAST_N`, Default **20**): nach jedem
  Archivieren (pro Run, siehe §5.4) werden ältere Runs über N komprimiert →
  `archive/runs/<run_id>.tar.gz`, dann Ordner gelöscht.
- **Soft-Cap `KEEP_COMPRESSED_LAST_N`** (ENV `FIRMA_ARCHIVE_KEEP_COMPRESSED_LAST_N`, Default
  **100**): von den komprimierten Archives werden die ältesten über 100 endgültig gelöscht.
  Begründung: „unbegrenzt komprimiert" wächst trotzdem irgendwann; 100 reicht für historische
  Analyse und bleibt bounded.

---

## 5. Integration / betroffene Dateien

1. **NEU** `engine/services/run_archive.py`
   - `class RunArchiver`
   - `async archive_run(run_id, controller, store, config)` — baut Manifest + Snapshots, schreibt
     `archive/runs/<run_id>/`.
   - `enforce_retention(config)` — `KEEP_LAST_N` + Kompression der älteren Runs; **wird am Ende
     von `archive_run()` pro Run aufgerufen** (kein separater Maintenance-Job).
   - `_collect_artifact_refs(run_id)` — walk `data/artifacts/<run_id>/`.
   - `_build_config_snapshot()` — liest `FIRMA_*`-Werte aus `engine/settings.py` + `os.environ`.
   - `attach_run_log_handler(run_id)` / `detach_run_log_handler(run_id)` — **einzige Logging-
     Plumbing-Änderung**: ein `FileHandler` auf `archive/runs/<run_id>/run.log` für die Run-Dauer
     (reversible, low risk). Verhindert, dass Logs nur auf Console landen.

2. **EDIT** Terminal-Hook an 3 Stellen (bestehender Code):
   - **Run-Start** (direkt nach `await controller.create_run(config)`, run_id bekannt):
     `run_archiver.attach_run_log_handler(run_id)` — startet `run.log`-Erfassung.
   - **Terminal** (nach der bestehenden `if status in ["COMPLETED","FAILED","CANCELLED"]:`-Erkennung):
     `await run_archiver.archive_run(run_id, controller, store, config)` dann
     `run_archiver.detach_run_log_handler(run_id)`.
   - Betroffene Dateien: `run_pi_mesh.py` (~545/550), `platform/run_pi_mesh.py` (~459/464),
     `run_snake.py` (~179/186).

3. **EDIT** `engine/settings.py` (zeile ~19, neben `LOG_DIR = ARCHIVE_DIR / "logs"`)
   - `ARCHIVE_RUNS_DIR = ARCHIVE_DIR / "runs"`
   - `KEEP_LAST_N = int(getenv("FIRMA_ARCHIVE_KEEP_LAST_N", "20"))`
   - `KEEP_COMPRESSED_LAST_N = int(getenv("FIRMA_ARCHIVE_KEEP_COMPRESSED_LAST_N", "100"))`

4. **EDIT (minimal, falls fehlend)** `engine/controller.py`
   - `get_run_summary(run_id)` → liefert `started_at`, `terminal_state`, `task_summary`,
     `failure_reason`, `summary_counters` (reixt bestehende `get_run_status` + Repository).
     Falls schon vorhanden: reuse, kein neuer Code.

---

## 6. `manifest.json` — minimales Schema

```json
{
  "run_id": "24fb7bbf-ea7a-4b53-a389-5e4348dc82ce",
  "app": "counter",
  "transport": "pimesh",
  "started_at": "2026-07-19T12:00:00Z",
  "terminal_state": "COMPLETED",
  "task_summary": [
    {"task_id": "task-1", "role": "CODER",    "state": "DONE", "review": "APPROVED"},
    {"task_id": "task-2", "role": "CODER",    "state": "DONE", "review": "APPROVED"},
    {"task_id": "task-3", "role": "REVIEWER", "state": "DONE", "review": "APPROVED"}
  ],
  "artifact_refs": [
    {"task_id": "task-1", "path": "data/artifacts/24fb7bbf-.../task-1/game.js", "bytes": 5181}
  ],
  "logs_path":         "archive/runs/24fb7bbf-.../run.log",
  "db_snapshot_path":  "archive/runs/24fb7bbf-.../db_snapshot.json",
  "config_snapshot": {
    "FIRMA_TRANSPORT": "pimesh",
    "FIRMA_MODE": "...",
    "SESSION_MODE": "off",
    "MAX_CONCURRENT_SPAWNS": 1,
    "PERSONA_ID": "default"
  },
  "archived_at": "2026-07-19T12:09:30Z"
}
```

---

## 7. Tests

### Unit — `tests/test_run_archive.py`
- **`test_archive_written_on_run_terminal()`**
  - Setup: Fake-`controller`/`store`, ein Run mit `terminal_state=COMPLETED`, ein Artefakt unter
    `data/artifacts/<run_id>/task-1/x.js`.
  - Act: `await RunArchiver.archive_run(...)`.
  - Assert: `archive/runs/<run_id>/manifest.json` existiert; `terminal_state == "COMPLETED"`;
    `artifact_refs` nicht leer **und** referenzierter Pfad existiert; `config_snapshot` enthält
    `FIRMA_TRANSPORT`.
- **`test_retention_deletes_old_archives_keep_last_n()`**
  - Setup: `KEEP_LAST_N=3`, lege 6 fake-Archive `archive/runs/run-1..6/` (aufsteigende mtime).
  - Act: `RunArchiver.enforce_retention()`.
  - Assert: genau 3 unkomprimierte Ordner bleiben (neueste 3); die 3 ältesten liegen als
    `run-N.tar.gz` vor und deren Ordner ist gelöscht.

### E2E
- Starte echten kleinen counter-Run ueber den **korrekten pimesh-Entrypoint** (`run_snake.py`
  verdrahtet `messenger_callback` und spawnnt echte `pi`-Worker; `run_pi_mesh.py` tut das in
  `main_logic` aktuell NICHT → nur Dispatch, kein Spawn → PLANNER-TIMEOUT):
  ```
  FIRMA_APP=counter FIRMA_TRANSPORT=pimesh FIRMA_MAX_CONCURRENT_SPAWNS=1 \
  FIRMA_REVIEWER_DUMMY=true SESSION_MODE=off python run_snake.py
  ```
- Assert nach `COMPLETED`:
  - `archive/runs/<run_id>/manifest.json` existiert.
  - `terminal_state == "COMPLETED"`.
  - `artifact_refs` zeigen auf existierende Dateien unter `data/artifacts/<run_id>/`.
  - `config_snapshot.FIRMA_TRANSPORT == "pimesh"`.
  - **Cleanup-Check:** Run-Session-Dir (außer `_base`) wurde wie gewohnt entfernt — das Archiv
    bleibt unberührt (H5 bewiesen).

---

## 8. Disziplin

- Erst Unit (`tests/test_run_archive.py`) grün, dann E2E (counter) bewiesen.
- Danach **Commit + Tag** `phase7-step1-run-archive-e2e-proven`.
- Keine Kernel-Änderung; beim Commit **nur** die Phase-1-Dateien (`run_archive.py`,
  Terminal-Hooks, `settings.py`, `controller.py`-Ergänzung, `tests/test_run_archive.py`) —
  keine anderen uncommitted Files mitgesweept.

---

## 9. Entscheidungen (FINAL — vom Freigebenden bestätigt)

1. **`KEEP_LAST_N` = 20** (ENV `FIRMA_ARCHIVE_KEEP_LAST_N`). Zusätzlich Soft-Cap
   **`KEEP_COMPRESSED_LAST_N` = 100** (ENV `FIRMA_ARCHIVE_KEEP_COMPRESSED_LAST_N`) für komprimierte
   Archives → bounded, historisch ausreichend.
2. **Run-Log: FileHandler pro Run** → `archive/runs/<run_id>/run.log` (canonical). Globales Log
   bleibt erlaubt; Archiv soll *self-contained enough* sein.
3. **DB-Snapshot (v1, schlank):** Run-Record + Task-States + `failure_reason` + Summary-Counters.
   **Nicht** alle Transition-Events (die bleiben in der DB; Archiv = Pointer + minimale
   Rekonstruktion). Portable replay = mögliches v2-Snapshot-Format (später).
4. **Retention Enforcement: pro Run** am Ende von `archive_run()` (deterministisch, kein extra
   Maintenance-Job).
