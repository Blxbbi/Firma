# Plan: PRD-Reviewer-Upgrade

**Datum:** 2026-07-31  
**Status:** Entwurf  
**Ziel:** REVIEWER von einer "Cosmetic-Check-Farce" zu einem echten Quality Gate machen, das PRD-Konformität prüft.

---

## 1. Problemstatement

### Aktueller Zustand
- REVIEWER prüft nur Code-Anwesenheit und oberflächliche Qualität
- Keine Prüfung gegen PRD-Anforderungen
- Keine Prüfung von Constraints (`localStorage`-Verbot, etc.)
- Review ist eine Farce: "Sieht gut aus → REVIEW_APPROVED"

### Gewünschter Zustand
- REVIEWER prüft CODER-Output gegen task-spezifische PRD-Checkliste
- Strukturierte Findings (PASS/FAIL pro Checklisten-Item)
- Bei FAIL → Task wird rejected → CODER muss nachbessern
- Doppelte Sicherheit: LLM-Review + deterministische Constraint-Checks

---

## 2. Architektur-Entscheide

### 2.1 Event-Namen
**Entscheid:** Verwende bestehende Events aus `engine/models.py`:
- `REVIEW_APPROVED` → Task genehmigt
- `REVIEW_FAILURE` → Task abgelehnt (mit strukturierten Findings)

**Begründung:** Keine neuen Event-Typen einführen, bestehende Logik wiederverwenden.

### 2.2 Checkliste als strukturiertes Feld
**Entscheid:** `review_checklist: List[str]` als Feld in `TaskDraftSchema` / `TaskDefinition`.

**Begründung:**
- Planner generiert Mini-Checkliste pro Task aus PRD
- Reviewer bekommt sie aus `task_definition.get('review_checklist', [])`
- Engine hat sie persistiert (nicht nur im Prompt versteckt)
- Verifier kann sie ebenfalls lesen

**Schema-Erweiterung:**
```python
# engine/models.py
class TaskDraftSchema(BaseModel):
    task_id: str
    role: AssignedRole
    description: str
    expected_artifacts: List[str]
    review_checklist: List[str] = Field(default_factory=list)  # NEU
    depends_on: List[str] = Field(default_factory=list)
```

### 2.3 Doppelte Prüfung: LLM + Verifier
**Entscheid:** Zwei unabhängige Prüfungen, beide müssen PASS = Task approved.

| Prüfung | Wer | Wie | Was |
|---------|-----|-----|-----|
| **LLM-Review** | REVIEWER Worker | Prompt mit Checkliste | Fachliche Konformität (PRD-Checkliste) |
| **Constraint-Check** | Verifier (Engine) | Grep-Check auf verbotene Patterns | Technische Constraints (`localStorage`, `fetch()`, etc.) |

**Begründung:**
- Reviewer: "Ich sehe kein localStorage — PASS"
- Verifier: "Zeile 42 enthält localStorage — FAIL"
- → Task wird rejected
- Redundanz ist kein Fehler, sondern ein Feature

---

## 3. Implementierungs-Schritte

### Schritt 1: Schema erweitern (`engine/models.py`)
**Aufwand:** 15 Min  
**Datei:** `engine/models.py`

**Änderungen:**
1. `TaskDraftSchema` um `review_checklist: List[str]` erweitern
2. Task-Definition beim Speichern persistieren
3. Task-Instantiator (`plan_instantiator.py`) passt Checkliste durch

**Akzeptanzkriterium:**
- Task mit `review_checklist` kann erstellt werden
- Checkliste wird in DB gespeichert
- Checkliste ist über `task_definition.get('review_checklist', [])` zugänglich

**Abhängigkeiten:** Keine

---

### Schritt 2: Constraint-Verifier bauen (`engine/services/verifiers/`)
**Aufwand:** 30 Min  
**Datei:** `engine/services/verifiers/constraint_verifier.py` (neu)

**Funktion:**
```python
FORBIDDEN_PATTERNS = {
    "localStorage": ["localStorage", "sessionStorage"],
    "fetch": ["fetch(", "XMLHttpRequest"],
    "cdn": ["cdn.", "unpkg.com", "jsdelivr.net"],
}

def verify_constraints(artifacts: dict) -> List[ConstraintViolation]:
    violations = []
    for filename, content in artifacts.items():
        for category, patterns in FORBIDDEN_PATTERNS.items():
            for pattern in patterns:
                if pattern in content:
                    violations.append({
                        "category": category,
                        "file": filename,
                        "pattern": pattern,
                        "line": find_line(content, pattern)
                    })
    return violations
```

**Akzeptanzkriterium:**
- Verifier erkennt `localStorage` in `app.js`
- Verifier erkennt `fetch()` in `app.js`
- Verifier erkennt CDN-Links in `index.html`
- Verifier schreibt Findings in strukturiertes Format

**Abhängigkeiten:** Keine

---

### Schritt 3: Reviewer-Prompt redesign
**Aufwand:** 30 Min  
**Datei:** `engine/providers/pi_provider.py` (Prompt-Generierung)

**Neuer Prompt-Aufbau:**
```
Du bist ein PRD-Reviewer. Prüfe die Umsetzung des CODERs gegen die PRD-Checkliste.

## Deine Aufgabe
1. Lies alle Dateien des Tasks: {expected_artifacts}
2. Prüfe JEDE Zeile der Checkliste:
{review_checklist}
3. Für jede Zeile schreibe:
   - ✅ PASS wenn erfüllt
   - ❌ FAIL wenn nicht erfüllt + konkrete Begründung
4. Wenn alle PASS → REVIEW_APPROVED
5. Wenn mindestens ein FAIL → REVIEW_FAILURE + Liste aller FAILs

## WICHTIG
- Sei konkret: "Step 1 hat keinen Welcome-Screen" statt "Code unvollständig"
- Nenne Dateinamen und Zeilen wenn möglich
- Keine Freitext-Beschwerden, nur faktische Findings
```

**Response-Format:**
```json
{
  "event": "REVIEW_APPROVED" oder "REVIEW_FAILURE",
  "checklist_results": [
    {
      "item": "Step 1 hat Welcome-Screen mit Logo",
      "status": "PASS" oder "FAIL",
      "note": "Konkrete Begründung"
    }
  ],
  "summary": "3/4 PASS — Task abgelehnt"
}
```

**Akzeptanzkriterium:**
- Reviewer schreibt strukturierte Findings
- Reviewer erkennt fehlende PRD-Elemente
- Reviewer schreibt `REVIEW_FAILURE` mit konkreter Begründung

**Abhängigkeiten:** Schritt 1 (Checkliste muss im Task vorhanden sein)

---

### Schritt 4: Planner anpassen (Checkliste generieren)
**Aufwand:** 45 Min  
**Dateien:**
- `workers/planner.py` (Prompt)
- `engine/services/plan_instantiator.py` (Checkliste extrahieren)

**Aufgabe:**
- Planner generiert pro Task eine Mini-Checkliste aus der PRD
- Checkliste wird als `review_checklist` in Task-Definition gespeichert

**Beispiel für Task 2:**
```json
{
  "task_id": "task-2",
  "review_checklist": [
    "Step 1 hat Welcome-Screen mit Logo und Headline",
    "Step 2 hat 5 Feature-Checkboxen",
    "KEIN localStorage in app.js",
    "KEIN fetch() in app.js"
  ]
}
```

**Akzeptanzkriterium:**
- Planner generiert Checkliste pro Task
- Checkliste ist spezifisch (keine generischen Items)
- Checkliste ist prüfbar (keine interpretierbaren Items)

**Abhängigkeiten:** Schritt 1 (Schema-Feld muss existieren)

---

### Schritt 5: Integration in Pipeline (`run_pi_mesh.py`)
**Aufwand:** 30 Min  
**Datei:** `run_pi_mesh.py`

**Ablauf:**
```
CODER → CODE_SUBMITTED
  ↓
Verifier: Constraint-Check (Grep)
  ↓
REVIEWER: LLM-Review (Checkliste)
  ↓
WENN REVIEW_FAILURE ODER Constraint-Violations:
  → Task wird rejected
  → CODER bekommt Feedback
  → Retry (max 1x)
SONST:
  → REVIEW_APPROVED
  → Nächster Task startet
```

**Akzeptanzkriterium:**
- Bei `REVIEW_FAILURE` wird Task rejected
- Bei Constraint-Violation wird Task rejected
- CODER bekommt strukturiertes Feedback
- Retry wird gestartet

**Abhängigkeiten:** Schritte 2, 3, 4

---

### Schritt 6: Erster Test-Run
**Aufwand:** 60 Min  
**Test-Szenario:**
- Task 2 aus bekanntem Run (`b1703a8e...`)
- Reviewer prüft gegen Mini-Checkliste
- Erwartung: Reviewer erkennt, dass Step 2 keine 5 Feature-Checkboxen hat

**Success-Criteria:**
1. Reviewer schreibt `REVIEW_FAILURE` statt `REVIEW_APPROVED`
2. Findings sind konkret ("Nur 3 Checkboxen, erwartet 5")
3. Constraint-Check erkennt `localStorage` in `app.js`
4. Task wird rejected → CODER retry

**Abhängigkeiten:** Alle vorherigen Schritte

---

### Schritt 7: Iteration & Verfeinerung
**Aufwand:** 30 Min  
**Aufgabe:**
- Prompt verfeinern (konkretere Formulierung)
- Checkliste verfeinern (mehr Details)
- Performance messen (wie viel länger dauert Review?)

**Abhängigkeiten:** Schritt 6 (Test-Run muss funktionieren)

---

## 4. Risk-Matrix

| Risiko | Wahrscheinlichkeit | Auswirkung | Mitigation |
|--------|-------------------|------------|------------|
| Reviewer versteht Checkliste nicht | Mittel | Mittel | Prompt mit Beispielen, klare Struktur |
| Reviewer schreibt trotz FAIL → APPROVED | Mittel | Hoch | Constraint-Check als Backup, Retry-Logik |
| Checkliste zu lang für Prompt | Niedrig | Mittel | Mini-Checkliste pro Task (max 5 Items) |
| Constraint-Check hat false positives | Niedrig | Niedrig | Whitelist für legitime Fälle |
| Performance-Overhead (2x LLM-Calls) | Niedrig | Niedrig | Reviewer nur bei Bedarf, nicht für alle Tasks |

---

## 5. Timeline

| Woche | Schritt | Status |
|-------|---------|--------|
| KW31 | 1. Schema erweitern | ✅ |
| KW31 | 2. Constraint-Verifier bauen | ✅ |
| KW31 | 3. Reviewer-Prompt redesign | ✅ |
| KW31 | 4. Planner anpassen | ✅ |
| KW31 | 5. Integration in Pipeline | ✅ |
| KW31 | 6. Erster Test-Run | ⬜ |
| KW32 | 7. Iteration & Verfeinerung | ⬜ |

---

## 6. Akzeptanzkriterien (Gesamt)

1. **Reviewer prüft PRD-Checkliste:** Reviewer schreibt `REVIEW_FAILURE` wenn Checkliste nicht erfüllt
2. **Reviewer schreibt konkrete Findings:** Keine "sieht gut aus"-Aussagen, sondern faktische Abweichungen
3. **Constraint-Check funktioniert:** Verifier erkennt `localStorage`, `fetch()`, CDN-Links
4. **Doppelte Prüfung:** Sowohl Reviewer als auch Verifier müssen PASS = Task approved
5. **Retry-Logik:** Bei `REVIEW_FAILURE` wird CODER-Retry gestartet (max 1x)
6. **Keine Regression:** Bestehende Runs funktionieren weiterhin

---

## 7. Offene Fragen

1. **Sollen alle Tasks einen REVIEWER bekommen?** 
   - Aktuell: Ja (task-1 bis task-4)
   - Option: Nur Tasks 2-4 (Task 1 ist Foundation, wird durch ScopeGuard geprüft)

2. **Soll Constraint-Check vor oder nach LLM-Review laufen?**
   - Vorher: Schneller Reject bei offensichtlichen Verstößen
   - Nachher: LLM kann Verstoß erklären
   - Empfehlung: Vorher (schneller)

3. **Soll Reviewer auch Code-Qualität prüfen?**
   - Aktuell: Nein (nur PRD-Konformität)
   - Später möglich: Separater Code-Reviewer
   - Empfehlung: Erst PRD-Check stabilisieren, dann Code-Qualität hinzufügen

---

## 8. Referenzen

- `engine/models.py` — Event-Enum, Task-Schema
- `engine/providers/pi_provider.py` — Reviewer-Prompt
- `engine/services/verifiers/` — Constraint-Verifier (neu)
- `workers/planner.py` — Checkliste generieren
- `docs/PRD_saas_wizard_complex.md` — Test-PRD

---

## 9. Änderungshistorie

| Datum | Version | Änderung |
|-------|---------|----------|
| 2026-07-31 | 0.1 | Initiale Plan-Version |
