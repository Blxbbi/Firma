# Firma Statusbericht — 2026-07-22

## Was wir fertig gebaut haben

### Phase 7 — Tool-Optimierung des REVIEWERs + Auditor-Extension (diese Session)

#### 1. Kernel-Side Timestamp-Repair (Bug-Fix)
**Commit `uncommitted` (in `run_pi_mesh.py`)**

**Problem**: Der REVIEWER-LLM gab manchmal den *Shell-Placeholder* `$(date -u +%Y-%m-%dT%H:%M:%S.%N+00:00)` als `timestamp` zurück → Guardian rejectet mit `SUBMISSION_INVALID_SCHEMA` → Task schlug nach 600s HARD_TIMEOUT fehl.

**Lösung**: `_repair_worker_response_timestamp()` in `run_pi_mesh.py` (und `run_snake.py`) erkennt literal shell placeholders und ersetzt sie mit `datetime.now(timezone.utc).isoformat()` vor `WorkerResponse.model_validate()`.

---

#### 2. Reviewer Tool-Policy (Optimierung)
**Commit `b39aa755` + Tag `reviewer-tools-restricted-proven`**

**Problem**: Der REVIEWER-Agent arbeitete wie ein iterativer CODER: er hatte `read`, `write`, `edit`, **`bash`** verfügbar → baute lange Tool-Chains (40–175 `read`-Calls + 22–87 `bash`-Calls pro Task) → **1.519 Turns, 1,23 Mio Token, 114s** pro Reviewer-Task.

**Lösung**:
- **Persona-Fix**: `pimesh/reviewing-crew/.pi/messenger/crew/agents/crew-worker.md` → Tools auf `read, write` reduziert
- **Prompt-Fix**: ONE-PASS-Contract ("Do NOT edit files. Do NOT iterate. Decide in ONE PASS.")
- **Architektur-Invariante dokumentiert**: Reviewer = Single-Pass-Validator (kein Iteration, kein Code-Change)

**Ergebnis**:
```
task-1 Reviewer:  1.519 Turns → 4 Turns  (–99,7 %)
task-2 Reviewer:  1.163 Turns → 4 Turns
task-3 Reviewer:  3.434 Turns → 4 Turns
Tokens gesamt:    ~1,23 Mio  → ~138k      (–87 %)
Laufzeit:          114s       → 18–30s     (–74 %)
```

---

#### 3. Phase 4 Auditor — Tool-Usage-Extension (Idee C)
**Commits `uncommitted` (in `engine/services/auditor.py` + `engine/services/run_archive.py`)**

**Problem**: Auditor hatte keine Sicht auf Tool-Nutzung pro Rolle → keine Metrik für "hat der Reviewer wirklich nur read/write benutzt?".

**Lösung**:
- `run_archive.py`: `_collect_tool_usage_by_task()` parst `worker.log`-Dateien unter `pimesh/<crew>/.pi/work/<run_id>/<task_id>/` und aggregiert `tool_execution_start`-Einträge je Task → `manifest.json` Feld `tool_usage_by_task`
- `auditor.py`:
  - §8 **"Tool Usage by Role"**: aggregierte Tool-Counts je Rolle
  - §9 **"Tool Policy Checks"**: prüft `REVIEWER` auf `edit==0` und `bash==0` → `POLICY VIOLATION` bei Verstoß

---

## Was wir in dieser Session gefixt haben

### Bug 1 — REVIEWER gibt Shell-Placeholder statt ISO-Timestamp zurück
**Symptom**: task-2 schlug fehl mit `SUBMISSION_INVALID_SCHEMA` (timestamp-Feld)
**Ursache**: LLM füllte das `timestamp`-Feld mit dem literal String `$(date -u +...)` statt mit einem echten ISO-8601-Datum → Schema-Validator rejectet.
**Fix**: Kernel-side repair in `run_pi_mesh.py` + `run_snake.py` (ersetzt placeholder vor Validation)
**Run**: `e9f7b88c-215e-4f59-aec8-9747f394a86b` → erstmalig 3/3 `REVIEW_APPROVED`

### Bug 2 — REVIEWER hat iterativ mit bash/edit gearbeitet
**Symptom**: task-1 Reviewer: 1.519 Turns, 1,23 Mio Token, 114s
**Ursache**: Reviewer-Persona erlaubte `bash` + `edit` → LLM baute Tool-Chains wie ein CODER
**Fix**: Tool-Entzug (nur `read, write`) + ONE-PASS-Prompt + Tool-Policy-Checks im Auditor
**Run**: `ef913b47-...` → 4 Turns, 138k Token, 18–30s pro Reviewer-Task

---

## Was es uns bringt

### Der Loop ist stabil + schnell (bewiesen)
```
Ordner (Counter-v1)
  → Ingest + Scope-Guards
  → Researcher (read-only Briefing)
  → Planner (Plan mit CODER-Tasks)
  → CODER (chirurgisches Edit)
  → Reviewer (4 Turns, Single-Pass)
  → Archiv + Audit (mit Tool-Policy-Proof)
  → Promote → Counter-v2
```

### Konkrete Beweise
| Metrik | Vorher (z. B. task-1 Reviewer) | Nachher |
|--------|--------------------------------|---------|
| Turns | 1.519 | **4** |
| Tokens | 1,23 Mio | **138k** |
| Laufzeit | 114s | **18–30s** |
| Tool-Calls (`bash`/`edit`) | 22–87 / Task | **0** |

### Phase 4 Auditor liefert Compliance-Proof
- `audit.md` enthält nun **§8 Tool Usage by Role** + **§9 Tool Policy Checks**
- Reviewer-Verstöße gegen `edit==0` / `bash==0` werden automatisch als `POLICY VIOLATION` markiert
- `manifest.json` speichert `tool_usage_by_task` für CI-Metriken

### Architektur-Invariante etabliert
- **REVIEWER = Single-Pass-Validator**: keine Iteration, kein Code-Change, nur Lesen + eine Response-Datei schreiben
- Bei Verstoß → `POLICY VIOLATION` im Audit → kein Block (report-only), aber sichtbar

---

## Was wir jetzt damit machen können

### Sofort
1. **Schnelle Reviews in Production** — 4 Turns statt 1.500+ bedeutet: Reviews dauern Sekunden statt Minuten
2. **Compliance-Metriken** — Auditor trackt automatisch Tool-Policy-Einhaltung je Rolle
3. **End-to-end-Stabilität** — 3/3 `REVIEW_APPROVED` Runs sind reproduzierbar (timestamp-repair + tool-restriction)

### Kurz bis mittelfristig
4. **CI-Metrik "tools usage by role"** — die Rohdaten liegen in `manifest.json` → können in Pipeline ausgewertet werden
5. **Run_snake.py harmonisieren** — der Worker-Simulator-Pfad (`run_snake.py`) trackt aktuell keine Tool-Calls; könnte nachgezogen werden
6. **CODER-token-Optimierung** — task-3 liegt bei ~138k Token / 18s (bereits verbessert von 522k / 97s), ggf. weitere Prompt-Tightening-Möglichkeit

### Architektur-Erkenntnisse
- **Kernel-side Reparatur > Worker-Prompt-Änderung** — der timestamp-fix zeigt: wenn Worker autonom sind, kann man Verhalten am Empfänger sicherer erzwingen als im Prompt
- **Tool-Policies skalieren** — was für REVIEWER funktioniert (read/write-only), kann für PLANNER/RESEARCHER analog gelten
- **Auditor als Compliance-Layer** — der Auditor ist jetzt nicht mehr nur "Dateien zählen", sondern auch "Policy-Einhaltung messen"

---

## Tag / Commit-Referenz

```
b39aa755 feat(reviewer): restrict tools to read/write, tighten spec, add tool-policy doc + tests
41c6c739 fix(pi-provider): write prompt to file instead of -p to avoid shell limits
6979a213 feat: spawn-semaphore lock-until-response + tests
b31718d1 fix: per-task worker.log + spawn log-collision integration test
6796f864 fix(phase3.1-F5): researcher worker_response recovery with guardrails

Tag: reviewer-tools-restricted-proven
Tag: loop-smoke-f4-proven (Run 8aeff60b-4ada-44e6-840a-a2cdf1d88e0b)
```

## Test-Status

```
tests/test_phase4_auditor.py                 3/3 PASS   (Unit: Tool-Usage + Policy-Check)
tests/test_phase4_auditor_integration.py     2/2 PASS   (Integration: Audit als Archive-Hook)
tests/test_run_archive.py                    OK
tests/test_run_archive_integration.py        INTEGRATION_OK
tests/test_review_artifact_selection.py      9/9 PASS   (Selective Artifact Loading)
tests/test_retry_scrub.py                    6/6 PASS   (Retry-Session-Scrub)
tests/test_pimesh_spawn.py                   ALL SPAWN TESTS PASS
```

## E2E-Proof

| Run-ID | Ergebnis | Besonderheit |
|--------|----------|--------------|
| `e9f7b88c-...` | 3/3 COMPLETE | Erstmalig alle Tasks → `REVIEW_APPROVED` (timestamp-repair) |
| `ef913b47-...` | 3/3 COMPLETE | Reviewer mit tool-restriction: 4 Turns/Task |
