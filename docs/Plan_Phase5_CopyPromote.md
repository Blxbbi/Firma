# Plan — Phase 5: Copy / Promote (Idee E/F)

- **Datum:** 2026-07-16
- **Branch:** `chore/clean-architecture`
- **Status:** Draft / NOT IMPLEMENTED
- **Vorgänger:** Phase 1 (RunArchiver), Phase 2 (Ingest+Baseline+Scope), Phase 3 (Researcher), Phase 4 (Auditor)
- **Scope-Entscheidung:** **(B) Runbook + optionales `tools/`-Script** (Empfehlung des Users). Das Script ist ein
  reiner, nicht-automatischer Copy-Helper **außerhalb des Kernels**; niemals Auto-Promote, niemals Original-Mutation.

---

## 1. Sinn / Grund

Mit Ingest (Kopie in workspace), Baseline+Scope-Verifier, Research-Brief, Run-Archiv + Auditor ist das
System now in der Lage, einen **menschlichen Promote-Entscheid** sauber zu unterstützen: Der Mensch sieht
Workspace/Deliverables/`archive/runs/<run_id>/audit.md` und entscheidet, ob die Änderung „befördert" wird.

Phase 5 ist **keine Engine-Logik**, sondern primär **Runbook/Policy + ein minimales, sicheres Tooling**.
Es geht darum, eine **Konvention** festzulegen (wie Projekte versioniert werden, „Original nie anfassen")
und das, was sich mechanisieren lässt, als **Feature** (Script) zu kapseln — strikt getrennt vom Kernel.

---

## 2. Konvention vs. Feature (Kern dieses Plans)

| Ebene | Was | Erzwungen durch | Ort |
|---|---|---|---|
| **Konvention** | Verzeichnis-Layout `Projects/<name>/<name>-Original` + `<name>-vN`; „Original nie anfassen"; Review-vor-Promote; Versions-Naming | Mensch (dokumentiert im Runbook) | `docs/Copy_Promote_Runbook.md` |
| **Feature** | Sicheres Copy + Provenance beim Promoto | Script mit Guardrails | `tools/promote_run.py` (außerhalb des Kernels) |

**Wichtig:** Keine der Konventionen wird im Kernel code-erzwungen. Firma verändert das Original nie,
weil es per Ingest ohnehin nur eine **Kopie** in `workspace/<run_id>/project` bearbeitet. Die Konvention
ist die menschliche Disziplin, das Original nicht als `FIRMA_PROJECT_DIR` zu setzen.

---

## 3. Non-Goals (hart)

- **KEIN** Auto-Promote (kein Hook, der nach Run automatisch nach `<name>-vN+1` schreibt).
- **KEINE** Mutation des Originals (Firma schreibt nur in `workspace/<run_id>/project`).
- **KEINE** FSM-/Engine-/Governance-Änderung.
- **KEIN** In-Place-Promote (das Tool schreibt NUR in ein **neues**, leeres Ziel-Verzeichnis).
- **KEIN** LLM im Promote-Tool.

---

## 4. Verzeichnis-Konvention (5.0 Runbook-Inhalt)

```
Projects/
  <name>/
    <name>-Original/        # menschlicher Source-of-Truth, FROZEN, nie FIRMA_PROJECT_DIR
    <name>-v1/              # 1. Arbeitskopie (Initial = Kopie von -Original)
    <name>-v2/              # nach Promote entstanden
    ...
```

Workflow:
1. `FIRMA_PROJECT_DIR=Projects/<name>/<name>-vN` setzen → Ingest kopiert nach `workspace/<run_id>/project`.
2. Prompt + Run starten (Researcher → Planner → Coder → Verifier/Guardian → Archiv + Auditor).
3. Prüfen: `archive/runs/<run_id>/audit.md`, Deliverables, Scope/Drift-Summary, Research-Brief.
4. **Manuelles Promote** (Mensch): `workspace/<run_id>/project` → `Projects/<name>/<name>-v(N+1)`
   (via `tools/promote_run.py` oder `cp`/`rsync`/Git-commit).
5. Nächster Run nutzt `<name>-v(N+1)` als Input.
6. `-Original` bleibt als Referenz/Baseline unangetastet.

Typische Fehler + „Never touch Original"-Regeln + Rollback (alte `-vN` behalten, nie löschen) → im Runbook.

---

## 5. Feature: `tools/promote_run.py` (5.1, minimal, NICHT im Kernel)

**Signatur:**
```
python tools/promote_run.py --run_id <run_id> --target_dir <Projects/.../vN+1>
```

**Was es tut:**
1. Liest `workspace/<run_id>/project` (Quelle = Firma-Ergebnis, read-only gelesen).
2. **Safety-Checks (hart, vor jedem Schreiben):**
   - `target_dir` darf **nicht existieren** (oder leer sein) → sonst **Refusal** (kein Overwrite).
   - `target_dir` darf kein absoluter/„.."-Pfad sein (Path-Traversal-Abwehr).
   - Quell-`workspace/<run_id>/project` muss existieren.
3. Kopiert rekursiv `workspace/<run_id>/project` → `target_dir` (nur neu, nie überschreiben).
4. Schreibt `target_dir/PROMOTED_FROM_RUN.txt`:
   ```
   run_id=<run_id>
   audit=archive/runs/<run_id>/audit.md
   promoted_at=<iso>
   ```
5. Schreibt/aktualisiert KEINE Änderung am Original, an Firma-State, an DB.
6. Exit-Codes: 0 = promoted, 2 = refused (safety), 3 = not-found.

**Was es NICHT tut:** nie Original anfassen, nie auto-run, nie in-place, kein LLM, keine Firma-Engine importieren.

---

## 6. Tests (nur wenn Tool gebaut wird — `tests/test_phase5_promote_tool.py`)

- `test_promote_copies_project_into_new_target`:
  Seed `workspace/<run_id>/project` (paar Dateien), rufe `promote_run.py` mit leerem `target_dir`,
  assert: target enthält alle Quell-Dateien, `PROMOTED_FROM_RUN.txt` vorhanden + korrekter run_id-Link.
- `test_promote_refuses_overwrite`:
  `target_dir` existiert schon (nicht leer) → Tool weigert sich (Exit 2), Ziel unverändert.
- `test_promote_refuses_traversal`:
  `target_dir` mit „.."-Sequenz → Refusal (Exit 2), nichts geschrieben.
- `test_promote_missing_source`:
  `workspace/<run_id>/project` fehlt → Exit 3, keine Seiteneffekte.

---

## 7. E2E „manual" Akzeptanz (Beweis, dass das Modell greift)

- Ein archivierter Run liegt vor: `archive/runs/<run_id>/audit.md` existiert (Phase 4).
- Danach: `python tools/promote_run.py --run_id <run_id> --target_dir <new>` → erfolgreich (Exit 0),
  `target_dir` hat Projekt-Kopie + `PROMOTED_FROM_RUN.txt`, Original unberührt.
- Dies ist kein Engine-E2E, sondern ein **Tool-E2E** (Dateisystem), deterministisch + LLM-frei.

---

## 8. Implementierungs-Schritte (Staged)

1. **Step5.0 — Runbook (Doku)**
   - `docs/Copy_Promote_Runbook.md` (Inhalt aus §4: Konvention, Workflow, Never-touch-Original, Fehler, Rollback).
   - Commit (nur Doku).
2. **Step5.1 — Promote-Tool (minimal, `tools/`)**
   - `tools/promote_run.py` (Safety-Checks + Copy + Provenance).
   - `tests/test_phase5_promote_tool.py` (4 Tests aus §6).
   - Commit + **Tag `phase5-copypromote-proven`** nach Green-Regression.

---

## 9. Risiken / Hürden

- **Konvention wird nicht code-erzwungen** → Runbook muss klar genug sein, dass ein Mensch sie befolgt.
  (Absicht: Kernel bleibt rein; Menschen behalten die Autorität über Versionierung.)
- **Tool darf nicht in-place schreiben** → harter „target must not exist" Check (kein Overwrite je).
- **Path-Traversal** → Normalisierung + Ablehnung absoluter/„.."-Pfade.
- **Original-Schutz** ist indirekt: Firma schreibt ohnehin nur in workspace; das Tool liest nur workspace
  und schreibt nur in neues target. Ein Versehen (Original als target setzen) wird durch den
  „target exists"→Refusal-Check abgefangen (Original ist nicht leer).

---

*Draft. Implementierung erst nach Freigabe (Step5.0 Doku, dann Step5.1 Tool → Unit → E2E → commit+tag).*
