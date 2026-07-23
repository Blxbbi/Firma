# Plan Phase 2 — Ordner-Ingest + Coder-Edit (Idee A)

**Status:** Draft / not implemented
**Datum:** 2026-07-19
**Branch:** `chore/clean-architecture`
**Baut auf:** `docs/Plan_Phase1_RunArchive.md` (Phase 1 = Run-Archiv, abgeschlossen + bewiesen, Tag `phase7-step1-run-archive-e2e-proven`)
**Vorgänger-Design:** `docs/Vision_Inkrementell_Researcher_Auditor.md` (Idee A, §2.4 H1/H2, §9 H1/H2/H3, §11 Q1–Q3)

---

## 0. Kontext / Sinn

Phase 1 hat die **Fundament-Sicherheit** geliefert: jeder Run ist am Terminal-State archiviert +
auditable. Phase 2 ist der **erste echte Produktwert**: Firma wird vom „from-scratch-Generator"
zum **iterativen Dev-Partner**. Statt neu aufzubauen, startet ein Run von einem **existierenden
Projektordner** (Kopie), der Planner liefert eine **Delta/Edit-Spec**, der Coder **editiert nur
erlaubte Dateien**, und ein deterministischer Verifier garantiert: **„Rest bleibt"**.

Die Mechanik ist exakt die Antwort auf die Invarianten §9 des Vision-Docs:
- **Kernel State Sovereignty** → der Kernel ist der *einzige* Schreiber in den Arbeitsbaum; der
  Coder *proponiert* nur via `artifacts[]` (push-only).
- **Edit-Contract (H1)** + **Baseline-Manifest (H2)** → deterministischer Guard gegen LLM-Drift,
  unabhängig davon, was das Modell „meint".

Phase 2 ist **bewusst vor Researcher (Phase 3)** und **Auditor (Phase 4)** angesiedelt: Researcher
braucht einen Ingest, um einen Ordner zu erkunden; Phase 2 schafft diesen Ingest.

---

## 1. Scope / Non-Goals

**In Scope (Phase 2):**
- Ordner-Ingest: Kopie eines bestehenden Projektordners nach `workspace/<run_id>/project/`.
- Baseline-Manifest: Hash pro Datei beim Ingest (exkl. Build-Artefakte).
- Edit-Contract-Schema `scope_files` / `protected_files` in der Task-Definition (`task-N.md`/`task-N.json`).
- Scope/Protected-Verifier: harte Kernel-Regel (kein Prompt-Alleinvertrauen).
- Kernel materialisiert `artifacts[]` einzig in den Arbeitsbaum (single-writer).
- `workspace/<run_id>/project/` als „laufende Codebase"; ArtifactStore behält Task-Snapshots.
- E2E-Beweis über ein Minimal-Projekt (3 Dateien, 1 Änderung).

**Non-Goals (explizit NICHT in Phase 2):**
- **Kein Researcher-Agent** (Idee B) → Phase 3. Phase 2 arbeitet ohne autonome Erkundung;
  der Planner bekommt den Ordner als Kontext direkt.
- **Kein Auditor** (Idee C) → Phase 4.
- **Kein Copy/Promote** (Idee E/F) → Phase 5 (Original wird in Phase 2 nie mutiert; nur die
  Workspace-Kopie).
- **Kein** Firma-interner Projekt-Snapshot-Engine-Feature. „Ordner = Wahrheit", Kernel hält
  keinen eigenen Projektzustand.
- **From-scratch-Runs bleiben unverändert**: Phase 2 greift nur, wenn `FIRMA_PROJECT_SRC` gesetzt ist.

---

## 2. Directory Model (Workspace vs. ArtifactStore) — *User-Punkt 1*

Zwei klar getrennte Welten (wie heute, nur um den Arbeitsbaum ergänzt):

| Pfad | Rolle | Besitzer | Inhalt |
|---|---|---|---|
| `workspace/<run_id>/project/` | **Laufende Codebase** (= „Wahrheit" für diesen Run) | **Kernel (single-writer)** | Kopie des Ingest-Ordners, vom Coder editiert |
| `data/artifacts/<run_id>/<task_id>/` | Versionierte Task-Snapshots | ArtifactStore (wie heute) | `ArtifactChange{path,action,content}` pro Task |
| `archive/runs/<run_id>/` | Run-Archiv (Phase 1) | RunArchiver | `manifest.json`, `baseline_manifest.json`, `post_edit_manifest.json`, `run.log`, … |

**Regeln:**
1. **CODER schreibt NUR via `artifacts[]`** (push-only). Der Kernel materialisiert die Dateien
   einzig in `workspace/<run_id>/project/…` (single-writer, Invariante §9).
2. `WorkerResponse.artifacts[]` referenziert **relative Pfade innerhalb `project/`** (keine absoluten
   Pfade; Traversal-Schutz wie im `ArtifactStore` heute: `Path(path).relative_from("/")`-Normalisierung).
3. **ArtifactStore persistiert weiterhin Snapshots pro Task** (heutiges Verhalten, `data/artifacts/…`)
   — unverändert. Die „laufende Codebase" ist aber der Workspace-Baum, nicht der ArtifactStore.
4. Dadurch wird die Hash-Manifest-Prüfung einfach + deterministisch: sie läuft über
   `workspace/<run_id>/project/`, nicht über den ArtifactStore.

**Neue Settings** (`engine/settings.py`):
```python
WORKSPACE_DIR = BASE_DIR / "workspace"
# in ensure_directories(): WORKSPACE_DIR.mkdir(...)
```

---

## 3. Schema-Änderungen (scope_files / protected_files) — *H1*

**Sinn/Grund:** Der Coder-Prompt „ändere nur scope_files" ist notwendig, aber nicht hinreichend.
Die Edit-Contract muss **strukturell** vorliegen, damit der deterministische Guard sie prüfen kann.

**`engine/models.py` — `TaskDefinition` (Pydantic) erhält optionale Felder:**
```python
class TaskDefinition(BaseModel):
    # ... bestehende Felder (role, prompt, ...) ...
    scope_files: List[str] = Field(default_factory=list)      # relative Pfade, die der Coder
                                                              # CREATE/UPDATE darf
    protected_files: List[str] = Field(default_factory=list)  # relative Pfade, die der Coder
                                                              # NICHT anfassen darf (jede Aktion)
    edit_mode: str = "auto"   # "auto" | "force_edit" | "force_create" (Override, s. §5)
```

**Semantik:**
- `scope_files`: erlaubte Ziele für CREATE/UPDATE. Datei nicht vorhanden + in `scope_files` → CREATE erlaubt.
- `protected_files`: jede Aktion (CREATE/UPDATE/DELETE) verboten. **`protected_files` hat Vorrang
  vor `scope_files`** (Überschneidung → protected gewinnt).
- Datei weder in `scope_files` noch in `protected_files`:
  - existiert im Baseline → **darf nicht geändert werden** (CODEBOOK-Drift).
  - existiert nicht im Baseline → **darf nicht neu erstellt werden** (unerwartete neue Datei).

**Dispatch (task-N.md / task-N.json):** Der Planner füllt `scope_files`/`protected_files` aus dem
Ordner-Kontext. Der Worker (Coder) sieht im Spec einen `## SCOPE`-Block (erlaubte + geschützte
Dateien + Working-Dir). Prompt-Hinweis reicht nicht — das Feld ist die autoritative Quelle.

---

## 4. Baseline-Manifest (Format + Exclusions + Service) — *User-Punkt 2 + Hasher-Entscheidung*

**Hasher-Entscheidung (beantwortet):** Der Hasher wird ein **eigener Service**
`engine/services/baseline_manifest.py` (testbar, wiederverwendbar für Researcher/Auditor). Konsistent
mit `run_archive.py` (eigener Service, Unit-testbar).

### 4.1 Format
```json
{
  "run_id": "<run_id>",
  "tree_root": "workspace/<run_id>/project",
  "algorithm": "sha256",
  "exclusions": [".git", ".pi", "node_modules", "__pycache__", "dist", "build", ".venv", "venv"],
  "files": {
    "index.html": "a1b2c3…",
    "style.css":  "d4e5f6…",
    "app.js":     "0a9b8c…"
  },
  "generated_at": "2026-07-19T15:00:00Z"
}
```

### 4.2 Was wird gehasht (hash-relevant)?
**Alle regulären Quelldateien.** Explizit **ausgeschlossen** (nur aus dem Manifest, nicht aus dem
Schutz): reine Build/Dependency-Caches:
- Verzeichnis-Pattern: `.git/`, `.pi/`, `node_modules/`, `__pycache__/`, `dist/`, `build/`,
  `.venv/`, `venv/`, `.mypy_cache/`, `.pytest_cache/`, `.idea/`, `.vscode/`

**Wichtig (User-Sorge „package-lock.json"):** Lockfiles (`package-lock.json`, `yarn.lock`,
`poetry.lock`, `requirements.txt`, `Pipfile.lock`) sind **hash-relevant** (NICHT ausgeschlossen).
Wenn so eine Datei sich ändert und nicht in `scope_files` steht → **VERIFY_FAILURE** (Drift).
Das löst die „warum hat sich package-lock geändert"-Diskussion deterministisch: sie *darf* sich nur
ändern, wenn sie explizit in `scope_files` gelistet ist.

### 4.3 Service-API
```python
class BaselineManifest:
    DEFAULT_EXCLUSIONS = [".git", ".pi", "node_modules", "__pycache__",
                          "dist", "build", ".venv", "venv", ".mypy_cache",
                          ".pytest_cache", ".idea", ".vscode"]

    @staticmethod
    def build(tree_root: str, exclusions=None) -> dict:
        """Walking tree_root, sha256 pro Datei (relativ), exclusions angewandt."""

    @staticmethod
    def diff(baseline: dict, current: dict) -> dict:
        """
        Returns: {
          "changed":   [rel_p],   # in beiden, hash differs
          "added":     [rel_p],   # nur in current
          "removed":   [rel_p],   # nur in baseline
        }
        """

    @staticmethod
    def save(path: str, manifest: dict) -> None: ...   # _write_json wie run_archive
```

`build` ist rein (kein DB, kein FS-Schreiben außer `save`) → Unit-testbar ohne Sideeffects.

---

## 5. Verifier-Regeln (Policy) — *User-Punkt 3 (harte Kernel-Regel) + Punkt 4 (Override)*

**Sinn/Grund:** Der Guard muss **deterministisch** sein. Egal was das LLM „meint" — die Prüfung
läuft über (a) die gemeldeten `artifacts[]` und (b) den tatsächlichen Workspace-Diff. Zwei Stufen
(belt-and-suspenders).

### 5.1 Stufe 1 — Submission-Schema (vor Persistenz)
Neuer Verifier `engine/services/verifiers/scope_verifier.py`, registriert in
`verification_registry` (key z. B. `"structural_scope"`).
- `artifacts` keine Liste / `path` kein relativer String / `action` nicht in `FileAction`
  → **`TaskEvent.SUBMISSION_INVALID_SCHEMA`** (Strukturfehler).
- `path` verweist auf absoluten Pfad oder versucht Traversal (`../`) → `SUBMISSION_INVALID_SCHEMA`.

### 5.2 Stufe 2 — Policy (Inhalt/Policy)
- `path` in `protected_files` (egal welche Aktion) → **`VERIFY_FAILURE`**, reason `PROTECTED_VIOLATION`.
- `path` nicht in `scope_files` UND existiert im Baseline (Änderung erlaubter Nicht-Scope-Datei)
  → **`VERIFY_FAILURE`**, reason `SCOPE_VIOLATION`.
- `path` nicht in `scope_files` UND nicht im Baseline (unerwartete neue Datei)
  → **`VERIFY_FAILURE`**, reason `UNEXPECTED_NEW_FILE`.
- `action == DELETE` und nicht explizit in `scope_files` als erlaubte Löschung gelistet
  → **`VERIFY_FAILURE`**, reason `DELETE_NOT_ALLOWED`.
- **Workspace-Diff (nach Materialisierung):** `BaselineManifest.diff(baseline, current)` zeigt
  irgendeine Änderung außerhalb `scope_files` → **`VERIFY_FAILURE`**, reason `WORKSPACE_DRIFT`.
  (Fängt auch den Fall, dass der Kernel selbst fehlerhaft materialisiert hat.)

> Warum `VERIFY_FAILURE` (nicht `SUBMISSION_INVALID_SCHEMA`) für Out-of-Scope/Polycy?
> Struktur ist ok, **Inhalt/Policy verletzt** → `VERIFY_FAILURE`. `SUBMISSION_INVALID_SCHEMA` nur
> für strukturell defekte Submissions.

### 5.3 Override (App-Config pro Task) — *User-Punkt 4*
`edit_mode` in `TaskDefinition` (Default `auto`):
- **`auto`** (Default): Pfad existiert → UPDATE (edit); Pfad fehlt → CREATE. Beides nur innerhalb
  `scope_files`.
- **`force_edit`**: Task darf **nur bestehende** Dateien editieren; jeder CREATE (Pfad nicht im
  Baseline) → `VERIFY_FAILURE` reason `FORCE_EDIT_NO_CREATE`.
- **`force_create`**: Task darf **nur neue** Dateien anlegen (Pfade nicht im Baseline); jeder UPDATE
  einer existierenden Datei → `VERIFY_FAILURE` reason `FORCE_CREATE_NO_EDIT`.
- **`protected_files` + beliebige Aktion → IMMER `VERIFY_FAILURE`** (`PROTECTED_VIOLATION`),
  **unabhängig von `edit_mode`**. Auch `force_edit` auf eine `protected_file` ist verboten (Policy).

---

## 6. Dispatch / Spec-Änderungen (task-N.md) — *User-Punkt 4 (fortges.)*

Das vom Planner erzeugte Spec (`tasks/task-<n>.md` + `.json`) erhält einen `## SCOPE`-Block:
```markdown
## SCOPE
Working-Dir: workspace/<run_id>/project/
Erlaubte Dateien (scope_files):
  - style.css
Geschützte Dateien (protected_files):
  - index.html
  - app.js
Edit-Mode: auto
```
Der Coder-Agent bekommt dies als Kontext (read-only auf den Baum, schreibt nur via `artifacts[]`).
Der Kernel liest `scope_files`/`protected_files`/`edit_mode` aus der Task-Definition, um Stufe 1/2
(§5) durchzusetzen. Prompt-Hinweis = Hilfe, **Feld = autoritative Regel**.

---

## 7. Ingest-Pipeline (Copy → Baseline → Spec)

Neuer Service `engine/services/ingest.py`:
```python
async def ingest_project(src: str, run_id: str) -> str:
    """
    Kopiert src rekursiv nach workspace/<run_id>/project/ (exclusions aus
    BaselineManifest.DEFAULT_EXCLUSIONS, damit .git/.pi/... nicht kopiert werden).
    Gibt project_root zurueck.
    """
```
Ablauf in `run_snake.py` / `run_pi_mesh.py` (nur wenn `FIRMA_PROJECT_SRC` gesetzt):
1. `create_run(config)`.
2. `project_root = await ingest_project(FIRMA_PROJECT_SRC, run_id)`.
3. `baseline = BaselineManifest.build(project_root)` → speichern als
   `archive/runs/<run_id>/baseline_manifest.json` (Audit, siehe §9).
4. Planner bekommt `project_root` als Kontext → erzeugt Delta-Spec mit `scope_files`/`protected_files`.
5. CODER editiert; Kernel materialisiert + Scope-Verifier (§5).
6. `post_edit = BaselineManifest.build(project_root)` → `archive/runs/<run_id>/post_edit_manifest.json`.

**Trigger:** Env `FIRMA_PROJECT_SRC` (absolut oder relativ zu cwd). Wenn **nicht** gesetzt →
from-scratch-Run (heutiges Verhalten, unverändert). Optional `FIRMA_MODE=incremental` als
Explizit-Marker, Default = incremental sobald `FIRMA_PROJECT_SRC` gesetzt.

---

## 8. Tests: Unit + E2E — *User-Punkt 5 (Minimal-Beispiel)*

### 8.1 Unit (`tests/test_baseline_manifest.py`)
- `test_build_hashes_deterministic`: gleiche Dateien → gleicher Hash (Wiederholbarkeit).
- `test_build_excludes_node_modules`: `node_modules/…` fehlt im Manifest.
- `test_diff_detects_changed_added_removed`: 3-Fall-Abdeckung.
- `test_lockfile_is_hash_relevant`: `package-lock.json` ist im Manifest (nicht exkludiert).

### 8.2 Unit (`tests/test_scope_verifier.py`)
- `test_protected_violation`: artifact auf `protected_files` → `VERIFY_FAILURE/PROTECTED_VIOLATION`.
- `test_scope_violation`: artifact außerhalb `scope_files` → `VERIFY_FAILURE/SCOPE_VIOLATION`.
- `test_unexpected_new_file`: neue Datei nicht in `scope_files` → `VERIFY_FAILURE/UNEXPECTED_NEW_FILE`.
- `test_force_edit_blocks_create`: `edit_mode=force_edit` + CREATE → `VERIFY_FAILURE/FORCE_EDIT_NO_CREATE`.
- `test_schema_error`: `artifacts` keine Liste → `SUBMISSION_INVALID_SCHEMA`.
- `test_workspace_drift`: künstlich veränderter Baum außerhalb scope → `VERIFY_FAILURE/WORKSPACE_DRIFT`.

### 8.3 E2E (Minimal-Projekt, *kein* Snake)
Fixture `tests/fixtures/phase2_project/` = 3 Dateien: `index.html`, `style.css`, `app.js`.
- **Positiv:** Prompt „Ändere NUR die Button-Farbe in style.css zu blau".
  Erwartung: `scope_files=[style.css]`, `protected_files=[index.html,app.js]`;
  genau **1 Datei** ändert Hash; `index.html`/`app.js` identisch; **VERIFY_SUCCESS**.
  Assert: `len(manifest["changed"]) == 1`, `manifest["changed"] == ["style.css"]`,
  `artifact_refs ⊆ scope_files`.
- **Negativ (Drift-Beweis):** CODER (oder craftete `worker_response`) versucht `app.js` zu ändern
  → **VERIFY_FAILURE/SCOPE_VIOLATION**; Baum unverändert (kein Drift persistiert).
- Kommando (bewiesener Entrypoint `run_snake.py`):
  ```
  FIRMA_PROJECT_SRC=tests/fixtures/phase2_project \
  FIRMA_TRANSPORT=pimesh FIRMA_MAX_CONCURRENT_SPAWNS=1 \
  FIRMA_REVIEWER_DUMMY=true SESSION_MODE=off python run_snake.py
  ```

### 8.4 Disziplin (wie Phase 1)
Unit → E2E → commit + tag. Keine other uncommitted Files in den Phase-2-Commit swept.

---

## 9. Archiv-Integration (Phase 1 nutzen)

`RunArchiver.archive_run` (Phase 1) wird um zwei Dateien ergänzt, wenn ein Baseline-Manifest existiert:
- `baseline_manifest.json` (aus §7 Schritt 3)
- `post_edit_manifest.json` (aus §7 Schritt 6)

Damit ist der „Rest bleibt"-Check **später auditierbar** (genau die Vision: Run-Archiv als
Backtrack-Basis). Kein neues Archiv-Format, nur zwei zusätzliche Dateien im bestehenden
`archive/runs/<run_id>/`-Baum. `manifest.json` erhält optional
`"baseline_manifest": "baseline_manifest.json"`, `"post_edit_manifest": "post_edit_manifest.json"`.

---

## 10. Akzeptanzkriterien (Phase 2 done)

1. `FIRMA_PROJECT_SRC` gesetzt → Run kopiert Ordner nach `workspace/<run_id>/project/`,
   `baseline_manifest.json` existiert.
2. `scope_files`/`protected_files`/`edit_mode` in `TaskDefinition` + im Spec (`task-N.md`).
3. CODER ändert nur `scope_files`; `protected_files` bleiben byte-identisch.
4. Out-of-Scope-Submissions → `VERIFY_FAILURE` (deterministisch, nicht nur Prompt).
5. `package-lock.json`/Lockfiles sind hash-relevant; Änderung außerhalb scope → Failure.
6. E2E Minimal-Beispiel: genau 1 Datei ändert Hash, 2 bleiben gleich, **VERIFY_SUCCESS**.
7. E2E Negativ: Drift-Versuch → **VERIFY_FAILURE**, Baum unverändert.
8. From-scratch-Runs (ohne `FIRMA_PROJECT_SRC`) verhalten sich wie vor Phase 2 (Regression-frei).

---

## 11. Risiken / Hürden (benannt)

- **R1 — Kernel als single-writer:** CODER darf Baum nicht selbst schreiben (nur via `artifacts[]`),
  sonst verletzt es Invariante §9. Umsetzung: CODER-cwd = read-only auf `project/`, Push-only.
- **R2 — Traversal/absolute Pfade:** `artifacts[].path` muss relativ + normalisiert sein (wie
  `ArtifactStore` heute); absolute/`../`-Pfade → `SUBMISSION_INVALID_SCHEMA`.
- **R3 — Großbaum-Performance:** `BaselineManifest.build` über große Repos (10k+ Dateien) —
  sha256-Walk. Unit-testbar, ggf. später Parallel-Hash. v1 serial ok.
- **R4 — Symlinks:** Build v1 folgt Symlinks nicht (nutscht sie als Datei mit Hash). Später
  explizit ausschließen falls nötig.
- **R5 — Edit-vs-Create bei unklarem Prompt:** `auto` löst es über Anwesenheit im Baseline; App-Config
  kann mit `force_edit`/`force_create` nachschärfen. Default auto bleibt.
- **R6 — Planner muss scope korrekt füllen:** Wenn Planner zu weit scope setzt, ist der Guard zu
  lasch. Gegenmaßnahme: Planner bekommt nur den Ordner-Kontext (kein „ rate mal"), und der
  Verifier prüft trotzdem hart gegen das, was der Planner gesetzt hat. Researcher (Phase 3) wird
  den scope später fundierter ableiten.

---

## 12. Rollout / Tags / Disziplin

Schrittweise, jedes mit Unit + E2E + commit + tag (wie Phase 1):
- `phase2-step1-ingest-baseline-unit` — `ingest.py` + `baseline_manifest.py` + Unit-Tests (build/diff/exclusions).
- `phase2-step2-scope-verifier-unit` — `scope_verifier.py` + Unit-Tests (§5 Regeln).
- `phase2-step3-spec-schema` — `TaskDefinition` + `task-N.md` SCOPE-Block + Planner-Füllung.
- `phase2-e2e-incremental-proven` — E2E Minimal-Beispiel (positiv + negativ) + Archiv-Integration.

**Tag-Politik:** Tag erst NACH E2E-Beweis („erst beweisen, dann taggen"). Andere uncommitted Phase-Files
werden NICHT in die Phase-2-Commits geswept.

---

## 13. Antwort auf offene Frage (Hasher-Ort)

**Entscheidung:** `engine/services/baseline_manifest.py` als **eigener Service** (nicht im Ingest-Modul).
- testbar (rein, keine DB/FS-Seiteneffekte außer `save`),
- wiederverwendbar für **Researcher** (Phase 3: erkundet Baum, vergleicht Snapshots) und
  **Auditor** (Phase 4: diff zwischen Runs),
- konsistent mit `run_archive.py` (eigener Service, Unit-testbar).
`ingest.py` bleibt für die Kopie zuständig und ruft `BaselineManifest.build` nur auf.
