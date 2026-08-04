# PiMesh — Status, Probleme & Optimierungs-Roadmap
**Stand:** 2026-07-27  
**Letzter erfolgreicher Run:** `406e291a-19b2-4d61-afa9-969970552db9` (COMPLETED, 742.7s, 7 Tasks)

---

## 1. Was aktuell funktioniert

### ✅ Stabiler Kern
- **Scheduler**: Event-basiertes Logging, keine Log-Spam (~3 Zeilen pro Tick)
- **Worker-Spawn**: `PiProvider.spawn_worker` mit `pi --mode json` funktioniert zuverlässig
- **Receiver-Loop**: Scannt `.pi/messenger/crew/` und `pi/messenger/crew/` (Fallback)
- **Phase-Governance**: `engine/governance.py` steuert sauber `RESEARCHING → PLANNING → CODING → VERIFYING → REVIEWING → COMPLETE`
- **Dummy-Reviewer**: `FIRMA_REVIEWER_DUMMY=true` umgeht LLM-Reviews deterministisch (praktisch 0 Tokens)

### ✅ Run-Ergebnis
- Alle 7 Tasks erfolgreich abgeschlossen
- ~140 KB an Web-Artefakten produziert (HTML/CSS/JS)
- Keine Timeouts, keine hängenden Workers
- Run-Archivierung + Compression alter Runs funktioniert

---

## 2. Was schlecht / teuer ist

### ❌ Token-Kosten (Hauptproblem)
| Run | Tasks | Tokens | Kosten-Position |
|-----|-------|--------|-----------------|
| 406e291a | 7 | **~3,5 Mio** | Sehr hoch für ~140 KB Output |

**Haupttreiber (korrigiert):**
1. **CODER-Tasks schreiben dieselben Dateien mehrfach neu** — das ist der größte Token-Killer
2. **Kein File-Ownership**: task-1 bis task-7 erzeugen alle `index.html`, `style.css`, `app.js` neu
3. **Voller Kontext pro CODER**: Jeder Worker lädt zu viel Projekt-Informationen
4. **Kein Context-Caching**: Dateien werden bei jedem Spawn neu gelesen

**Wichtig:** Der **REVIEWER** ist im Dummy-Modus **kein Token-Treiber**. Die ~3,5 Mio Tokens kommen **fast ausschließlich von den CODER-Tasks**.

### ❌ Wiederholtes Neuschreiben derselben Dateien
| Task | Schreib-Aktionen | Problem |
|------|------------------|---------|
| task-1 | `index.html` | OK (Owner) |
| task-2 | `index.html + style.css` | **index.html schon vorhanden** |
| task-3 | `index.html + style.css + app.js` | **index.html + style.css schon vorhanden** |
| task-4 | `architecture.html` | OK (eigene Datei) |
| task-5 | `index.html + style.css` | **nochmal neu** |
| task-6 | `index.html + style.css + app.js` | **nochmal neu** |
| task-7 | `index.html + style.css + app.js` | **nochmal neu** |

**Effekt:** 7 Tasks = 7× denselben Projektzustand neu generieren → massiver Token-Verbrauch.

---

## 3. Konkrete Optimierungs-Ideen

### 3.1 File Ownership erzwingen (P0 — Haupthebel)
**Idee:** Jede Datei hat genau einen Owner-Task.

```python
# PLAN_SUBMITTED → Ownership-Validator
def validate_file_ownership(plan_draft):
    ownership = {}  # path -> [task_ids]
    
    for task in plan_draft.tasks:
        if task.role == "CODER":
            for artifact in task.expected_artifacts:
                path = artifact.path
                ownership.setdefault(path, []).append(task.id)
    
    violations = []
    for path, task_ids in ownership.items():
        if len(task_ids) > 1:
            violations.append(
                f"File ownership violation: `{path}` is owned by tasks {task_ids}. "
                f"Each file must be produced by exactly one CODER task."
            )
    
    if violations:
        return PLAN_REJECTED, violations
    return PLAN_APPROVED, []
```

**Regeln:**
- Jede Datei darf nur von **einem** CODER-Task geschrieben werden
- Spätere Tasks sind **edit-only** an klaren Stellen (oder arbeiten in neuen Dateien)
- **V1: keine Ausnahmen** (später: `OWNERSHIP_ALLOW_MULTIWRITE = ["README.md"]`)

**Effekt:** ~40-50% weniger Tokens, weil Re-Explain/Re-Write entfällt.

### 3.2 Planner-Prompt anpassen (P0)
**Prompt-Änderung:**
- "You MUST assign each output file to exactly one CODER task (file owner)."
- "Do not repeat `index.html`/`style.css`/`app.js` in multiple tasks."
- "If you need integration, put integration into the owner task."

### 3.3 Context-Reduktion pro CODER (P1)
**Idee:** Worker bekommen nur was sie brauchen.

| Aktuell | Optimiert |
|---------|-----------|
| Gesamtes Projekt gelesen | Nur Task-spezifische Dateien |
| Alle vorherigen Tasks geladen | Nur direkte Dependencies |
| System-Prompt + Regeln + Beispiele | Nur aktuelle Regeln |

**Effekt:** 30-50% weniger Input-Tokens pro Worker.

### 3.4 Skript-basierte Runtime-Checks (P1 — optional)
**Idee:** Deterministische Checks vor LLM-Review.

```bash
node --check app.js  # JS-Syntax
# oder Headless-Browser smoke:
playwright test --browser=chromium --headless smoke.js
```

**Checks:**
- JS-Syntax valid?
- Seite lädt ohne Console errors?
- CSS wird geladen?
- Basis-Elemente existieren?

**Effekt:** 0 Tokens für technische Prüfungen, aber nur sinnvoll wenn Reviewer nicht dummy ist.

### 3.5 Prompt-Kompression (P2 — sekundär)
**Idee:** Kürzere, präzisere Prompts.

| Aktuell | Ziel |
|---------|------|
| ~800-1200 Zeichen System-Prompt | ~400-600 Zeichen |
| Wiederholungen | Klare Regeln |

**Effekt:** 20-30% weniger Input-Tokens, aber **nur** wenn Ownership bereits greift.

---

## 4. Review-Architektur: richtig gewichtet

### ❌ Frühere Annahme (korrigiert)
"Reviewer reduzieren = viele Tokens sparen"

### ✅ Richtig
- **REVIEWER_IS_DUMMY=true** → Reviewer ist praktisch kostenlos (kein LLM-Call)
- **Echter Reviewer** sollte nur bei kritischen Tasks aktiv werden (Integration, Security)
- **Skript-Verifikation** sollte technische Checks übernehmen (0 Tokens)

**Fazit:** Reviewer-Architektur ist **kein P0** für Token-Einsparung.

---

## 5. Priorisierte Umsetzung

### P0 — Sofort (diesen Run noch)
- [x] `REVIEWER_IS_DUMMY=true` als Default setzen (kein Token-Effekt, aber sauberer)
- [ ] **File Ownership erzwingen** in `engine/guardian.py` oder `engine/scheduler.py`
  - `validate_plan_draft()`: Ownership-Check vor `PLAN_APPROVED`
  - Klare Fehlermeldung mit conflicting files + task_ids
- [ ] **Planner-Prompt anpassen** (file owner pro Datei)
- [ ] `tmp_live_test.py` IndexError fixen (Bug im Testskript)

### P1 — Diese Woche
- [ ] **Tests bauen**:
  - `test_plan_rejected_on_duplicate_expected_artifacts_across_coder_tasks()`
  - `test_plan_accepts_unique_ownership()`
  - `test_plan_reject_message_contains_conflict_file_and_task_ids()`
- [ ] **Context-Reduktion pro CODER**: Nur staged project + scope files + acceptance criteria
- [ ] **Optional**: JS-Syntax-Check / Headless-Smoke als deterministischen Verifier

### P2 — Nächste Woche
- [ ] Prompt-Templates kürzen (sekundär)
- [ ] Context-Caching (nice-to-have, aber Ownership löst 80%)
- [ ] Token-Metriken pro Run ausgeben (Ziel: <1M Tokens für 7 Tasks)

---

## 6. Messbare Ziele

| Metrik | Aktuell | Ziel (nach Optimierung) |
|--------|---------|-------------------------|
| Tokens pro Run | ~3,5 Mio | <1,5 Mio (-57%) |
| Datei-Rewrites pro Run | ~7× index.html/style.css/app.js | 1× je Datei |
| Input-Tokens pro CODER | ~100-200K | ~50-80K (-50%) |
| Laufzeit pro Task | ~60-120s | ~30-60s |
| Log-Zeilen pro Tick | 3-5 | 1-2 |

---

## 7. Offene Fragen

1. **Soll der Reviewer komplett abgeschafft werden** oder nur reduziert?
   - Aktuell: Dummy-Reviewer = `REVIEW_APPROVED` sofort (0 Tokens)
   - Option A: Abschaffen, nur Verifikation behalten
   - Option B: Behalten, aber nur bei kritischen Tasks

2. **Welche technischen Checks sind wirklich nötig?**
   - JS-Syntax: `node --check` (einfach)
   - Browser-Smoke: Playwright (optional, tricky auf Windows)
   - HTML5-W3C: akademisch, weniger wertvoll als Browser-Smoke

3. **Soll es einen "Quality-Gate" geben** bevor ein Task als COMPLETE markiert wird?
   - Z.B.: Mindestens 1 sauberer Review pro 3 Tasks
   - Oder: Am Ende des Runs ein Integrationstest

---

## 8. Nächste Schritte

1. ✅ Dokument aktualisieren (diese .md)
2. **P0 implementieren**: File Ownership Validator + Planner-Prompt
3. **Tests bauen** (3 Testfälle wie oben)
4. **Proof-Run**: Gleiche Website mit disjunkten `expected_artifacts`, Token-Ziel <1,5M

---

## Anhang: Run 406e291a — Kurz-Statistik

| Task | Rolle | Turns | Total Tokens | Artefakte |
|------|-------|-------|--------------|-----------|
| e1db3728 | RESEARCHER | 7 | 237.158 | research/brief.md |
| 2b3eb30c | PLANNER | 6 | 188.349 | plan_draft.json |
| task-1 | CODER | 5 | 124.937 | index.html |
| task-2 | CODER | 10 | 399.131 | index.html, style.css |
| task-3 | CODER | 15 | 534.903 | index.html, style.css, app.js |
| task-4 | CODER | 5 | 165.693 | architecture.html |
| task-5 | CODER | 7 | 427.377 | index.html, style.css |
| task-6 | CODER | 13 | 628.320 | index.html, style.css, app.js |
| task-7 | CODER | 12 | 831.629 | index.html, style.css, app.js |
| **GESAMT** | | **~80** | **~3,5 Mio** | **~140 KB** |

**Erkenntnis:** task-7 war mit 831K Tokens der teuerste einzelne Task — wahrscheinlich wegen finalem Polish + Accessibility-Audit.
