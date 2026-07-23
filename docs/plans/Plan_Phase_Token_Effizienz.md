# Plan Phase Token-Effizienz

**Status:** Entwurf  
**Datum:** 23.07.2026  
**Betroffene Systeme:** `run_pi_mesh.py`, `engine/transport/pi_mesh_transport.py`, `engine/services/auditor.py`, Crew-Personas  
**Ziel:** Token-Verbrauch pro Run um ~60-70% senken, ohne Funktionsverlust oder Verlust der Interpretierbarkeit  
**Nicht-Ziele:** Delta-Context, Prompt-Template-Layer, Architektur-Umbauten jenseits von Contracts und Policies

---

## 1. Kontext und Ausgangslage

### 1.1 Baseline (Run `ce5e5edb`, 23.07.2026)

| Task | Turns | Gesamt-Tokens | Input | Output | cacheRead |
|------|-------|---------------|-------|--------|-----------|
| task-1 | 17 | 1.688.125 | 150.703 | 58.254 | 1.479.168 |
| task-2 | 10 | 515.876 | 120.594 | 13.330 | 381.952 |
| task-3 | 8 | 518.552 | 143.768 | 28.928 | 345.856 |
| **Summe** | **35** | **2.722.553** | **415.065** | **100.512** | **2.207.976** |

**cacheRead-Anteil am Gesamtverbrauch:**
- task-1: **87,6%**
- task-2: **74,1%**
- task-3: **66,7%**

### 1.2 Ursachen-Hierarchie

**Primär (70-80% des Overheads)**
1. Kein ONE-PASS-Vertrag für CODER/PLANNER/RESEARCHER
2. Kein Hard-Turn-Limit
3. cacheRead-Explosion durch Iteration

**Sekundär (20-30% des Overheads)**
4. Übergroßer Prompt bei CODER
5. Keine Scope-Grenze
6. Tool-Schleifen ohne Konsequenz

**Tertiär (10-20% des Overheads)**
7. Keine Tool-Result-Kürzung
8. Kein Kontext-Budget pro Rolle

### 1.3 Wichtigste Erkenntnis

> Das Problem ist nicht "die LLMs iterieren zu viel" — das Problem ist "die LLMs dürfen iterieren ohne Konsequenz".

Jede Iteration kostet Tokens, und weil der Context mitwächst, wird jede Iteration teurer als die vorherige.

---

## 2. Leitprinzipien für die Umsetzung

### 2.1 Keine Interpretation ohne Messung

Bevor Limits eingeführt werden, muss die Basislinie sauber gemessen werden. Jede Änderung muss in `audit.md` und `audit.json` sichtbar sein.

### 2.2 Constraints vor Performance

Zuerst Contracts und Policies, dann Feinoptimierungen. Ohne harte Verträge ist jede Prompt-Kürzung nur Symptombekämpfung.

### 2.3 Rollenspezifische Policies statt One-Size-Fits-All

CODER from-scratch und CODER ingest/edit haben unterschiedliche Anforderungen. Eine globale "nur write"-Policy würde Ingest/Edit-Mode zerstören.

### 2.4 Keine invasiven Architekturen v1

Delta-Context, Prompt-Template-Layer, State-Machine für Context-Management sind für später. Sie helfen nicht, wenn das Grundproblem (Iteration ohne Grenze) nicht gelöst ist.

---

## 3. Korrigierte Priorisierung (Berater-Feedback integriert)

### 3.1 Warum die ursprüngliche Reihenfolge riskant war

- **Schritt 1+2+3 parallel:** Verliert Interpretierbarkeit. Wenn Turn-Limit, ONE-PASS und Tool-Policy gleichzeitig aktiviert werden, kann man nicht mehr isolieren, welche Maßnahme welchen Effekt hat.
- **"CODER nur write":** Kontraproduktiv für chirurgisches Editieren. Der Coder muss bestehende Dateien lesen können, sonst wird "minimal diff" zum Rewrite.
- **Hard Turn-Limit als TASK_FAILED:** Kann zu unnötigen Retries führen, wenn das Limit zu streng ist.

### 3.2 Korrigierte Reihenfolge

| Schritt | Fokus | Risiko | Effekt |
|---------|-------|--------|--------|
| **Schritt 1** | Turn-Zählung + Telemetrie | Sehr niedrig | Messbar |
| **Schritt 2** | ONE-PASS Contract für CODER | Niedrig | Token-Reduktion ohne Funktionsverlust |
| **Schritt 3** | Tool-Policy für CODER mode-spezifisch | Mittel (nach Schritt 2) | Feinjustierung |

---

## 4. Schritt 1 — Turn-Zählung und Telemetrie

**Status:** Noch nicht implementiert  
**Ziel:** Harte Zahlen ohne Verhaltensänderung  
**Aufwand:** 1-2 Stunden

### 4.1 Was wird gemessen

| Metrik | Quelle | Aggregation |
|--------|--------|-------------|
| `turn_start` Count | `worker.log` pro Task | `(run_id, task_id, role)` |
| Tool-Calls (read/write/edit/bash) | `worker.log` | Pro Rolle, pro Task |
| Input/Output/CacheRead Tokens | `worker.log` | Pro Rolle, pro Task |
| Context-Wachstum über Turns | `worker.log` | Pro Task |

### 4.2 Wo wird es implementiert

**Option A (empfohlen): Auditor/Archiver**
- `engine/services/auditor.py`: Erweitere `_collect_tool_usage_by_task()` um Turn-Zählung
- `engine/services/run_archive.py`: Schreibe Turn-Zahlen in `audit.md` und `audit.json`
- Vorteil: Zentral, bereits vorhanden, keine Änderung am Worker-Verhalten

**Option B: Receiver-Loop**
- `run_pi_mesh.py`: Zähle `turn_start` Events während des Runs
- Vorteil: Echtzeit, aber invasiver

**Entscheidung:** Option A, weil sie risikofrei ist und die Daten bereits archiviert werden.

### 4.3 Akzeptanzkriterien

- [ ] `audit.md` enthält pro Task: `turns=...`
- [ ] `audit.json` enthält pro Task: `turn_count`, `tool_calls`, `token_usage`
- [ ] Unit-Test: Künstlicher `worker.log` mit 3 `turn_start` → `count==3`
- [ ] Integration-Test: Echter Run → `audit.md` enthält Turn-Zahlen

### 4.4 Auswirkungen

Keine. Rein observativ. Ändert kein Worker-Verhalten.

---

## 5. Schritt 2 — ONE-PASS Contract für CODER

**Status:** Noch nicht implementiert  
**Ziel:** Token-Reduktion um 40-60% bei CODER ohne Funktionsverlust  
**Aufwand:** 1-2 Stunden

### 5.1 Contract-Definition

```
Du arbeitest in ONE-PASS:
- Lies die Task-Definition und die staged Projektdateien (falls vorhanden).
- Erlaubt: read() VOR dem ersten write().
- Verboten: read() NACH dem ersten write().
- Verboten: edit(). Schreibe die Datei vollständig neu (write).
- Verboten: bash() zur Selbstprüfung.
- Wenn unklar → TASK_FAILED statt iterieren.
```

**Begründung:**
- `read` vor `write`: Notwendig für Ingest/Edit-Mode, um bestehende Dateien zu verstehen
- Kein `read` nach `write`: Verhindert Selbstprüf-Schleifen
- Kein `edit`: Verhindert iterative Korrekturen. Lieber einmal vollständig schreiben.
- Kein `bash`: Keine Notwendigkeit für Selbstprüfung

### 5.2 Wo wird es implementiert

**Prompt-Ebene:**
- `engine/transport/pi_mesh_transport.py`: CODER-Spec um ONE-PASS-Regeln ergänzen

**Persona-Ebene:**
- `pimesh/coding-crew/.pi/messenger/crew/agents/crew-worker.md`: Tool-Policy aktualisieren

### 5.3 Akzeptanzkriterien

- [ ] CODER-Prompt enthält ONE-PASS-Regeln
- [ ] REVIEWER-Prompt prüft ONE-PASS-Einhaltung (Turns <= 6 für CODER)
- [ ] E2E-Test: CODER task-1 schafft Website in max 6 Turns
- [ ] Keine Funktionsverluste bei Ingest/Edit-Mode

### 5.4 Auswirkungen

**Positiv:**
- 40-60% weniger Tokens bei CODER
- Weniger Iterationen = kürzere Runs
- Klarere Verantwortung: CODER liefert fertiges Ergebnis

**Risiko:**
- Bei sehr komplexen Tasks könnte ONE-PASS zu TASK_FAILED führen
- Mit previous_feedback + Retry ist das beherrschbar

---

## 6. Schritt 3 — Tool-Policy für CODER mode-spezifisch

**Status:** Noch nicht implementiert  
**Ziel:** Feinjustierung der Tool-Erlaubnisse  
**Aufwand:** 1-2 Stunden (nach Schritt 2)

### 6.1 Zwei Profile

#### CODER from-scratch

| Tool | Erlaubt | Begründung |
|------|---------|------------|
| `read` | ✅ Vor dem ersten write | Task-Spec lesen |
| `write` | ✅ | Dateien erstellen |
| `edit` | ⚠️ Vermeiden | Lieber rewrite full file |
| `bash` | ❌ Standardmäßig | Keine Selbstprüfung |

#### CODER ingest/edit

| Tool | Erlaubt | Begründung |
|------|---------|------------|
| `read` | ✅ Vor und nach write | Bestehende Dateien verstehen |
| `write` | ✅ | Dateien erstellen/überschreiben |
| `edit` | ✅ | Chirurgisches Editieren |
| `bash` | ⚠️ Optional | Nur wenn explizit in Task erlaubt |

### 6.2 Umsetzung

**Prompt-Anpassung:**
- `engine/transport/pi_mesh_transport.py`: Mode-spezifische Tool-Listen im CODER-Prompt

**Persona-Anpassung:**
- `pimesh/coding-crew/.pi/messenger/crew/agents/crew-worker.md`: Zwei Tool-Profile

**Environment-Flag:**
- `FIRMA_CODER_TOOLS=write_only` (experimentell, für sehr kleine Tasks)

### 6.3 Akzeptanzkriterien

- [ ] from-scratch Coder nutzt nur write + read (vor write)
- [ ] ingest/edit Coder nutzt read + write + edit
- [ ] Keine Funktionsverluste bei bestehenden Ingest/Edit-Tasks
- [ ] Audit zeigt Tool-Verteilung pro Mode

---

## 7. Schritt 4 — Load-only-expected-artifacts vollständig aktivieren

**Status:** Teilweise implementiert in `run_pi_mesh.py`  
**Ziel:** Kein unnötiges Laden von Artefakten bei REVIEWER  
**Aufwand:** 1 Stunde

### 7.1 Aktueller Stand

In `run_pi_mesh.py`:
- `_review_target_paths()` extrahiert Pfade aus `expected_artifacts`
- `_load_artifacts_for_review()` lädt nur diese Pfade (Strategy 1)
- Fallback Strategy 2 lädt alle Dateien im artifact directory, wenn `expected_artifacts` fehlt

### 7.2 Problem mit Strategy 2

Wenn `expected_artifacts` nicht gesetzt ist, wird der gesamte Artefakt-Ordner geladen — das macht die Optimierung zunichte.

### 7.3 Umsetzung

- Option A: Strategy 2 komplett entfernen (hart, aber sicher)
- Option B: Strategy 2 hinter Flag `FIRMA_REVIEW_LOAD_ALL_ARTIFACTS=1` stellen (empfohlen für v1)

### 7.4 Akzeptanzkriterien

- [ ] REVIEWER lädt nur Dateien aus `expected_artifacts`
- [ ] Fallback nur mit aktivem Flag
- [ ] Token-Reduktion messbar in `audit.md`

---

## 8. Schritt 5 — Tool-Result-Kürzung

**Status:** Noch nicht implementiert  
**Ziel:** 10-20% Token-Reduktion bei großen Tool-Outputs  
**Aufwand:** 1 Stunde

### 8.1 Umsetzung

Wenn Tool-Result größer als X Zeilen → kürze auf first 50 + last 50 + Summary.

```
if len(tool_result) > 200:
    tool_result = tool_result[:100] + "\n... [gekürzt] ...\n" + tool_result[-100:]
```

### 8.2 Wo

- `engine/transport/pi_mesh_transport.py`: Kürzung in Tool-Result-Verarbeitung

### 8.3 Akzeptanzkriterien

- [ ] Große Tool-Results werden gekürzt
- [ ] Keine Funktionsverluste bei regulären Tasks

---

## 9. Schritt 6 — Prompt-Kürzung für PLANNER

**Status:** Noch nicht implementiert  
**Ziel:** 20-30% Token-Reduktion bei PLANNER  
**Aufwand:** 2 Stunden

### 9.1 Umsetzung

- Keine History
- Keine fremden Tasks
- Nur Research-Brief + aktuelle Task-Definition

### 9.2 Wo

- `engine/transport/pi_mesh_transport.py`: PLANNER-Spec kürzen

### 9.3 Akzeptanzkriterien

- [ ] PLANNER-Prompt enthält nur notwendige Informationen
- [ ] Keine Funktionsverluste bei Plan-Erstellung

---

## 10. Erwartete Ergebnisse nach Umsetzung

| Maßnahme | Token-Reduktion | Geschätzte neue Token-Zahl |
|----------|----------------|---------------------------|
| Aktuell (Baseline) | — | 2,72M |
| + Schritt 1 (Telemetrie) | 0% (nur Messung) | 2,72M |
| + Schritt 2 (ONE-PASS CODER) | 40-60% | 1,09M - 1,63M |
| + Schritt 3 (Tool-Policy CODER) | 10-20% | 870k - 1,46M |
| + Schritt 4 (Load-only-expected) | 20-30% | 700k - 1,17M |
| + Schritt 5 (Tool-Result-Kürzung) | 10-20% | 600k - 1,05M |
| + Schritt 6 (Prompt-Kürzung PLANNER) | 20-30% | 500k - 840k |
| **Gesamt (konservativ)** | **~60-70%** | **~800k - 1,1M** |

**Hinweis:** Die Zahlen sind Schätzungen. Schritt 1 liefert die echten Baseline-Daten, um die Effekte der subsequenten Schritte zu messen.

---

## 11. Was wir explizit NICHT machen

### 11.1 Delta-Context

**Warum nicht:** Over-Engineered für den aktuellen Stack. Bei 17 Turns ist der Delta fast so groß wie der Full-Context. Außerdem bräuchte man einen State-Machine für Context-Management — viel Architektur für wenig Gewinn.

### 11.2 Prompt-Template-Layer

**Warum nicht:** Netto wenig Gewinn. Es ist ein Architektur-Thema, kein Performance-Fix. Es spart 10-20% — aber erst wenn das Turn-Problem gelöst ist.

### 11.3 "Write-only Coder" als Default

**Warum nicht:** Zerstört Ingest/Edit-Mode. Der Coder muss bestehende Dateien lesen können, sonst wird "chirurgisch editieren" zum Rewrite.

---

## 12. Zeitplan und Verantwortlichkeiten

| Schritt | Aufgabe | Aufwand | Priorität |
|---------|---------|---------|-----------|
| 1 | Turn-Zählung + Telemetrie | 1-2h | 🥇 SOFORT |
| 2 | ONE-PASS Contract für CODER | 1-2h | 🥇 SOFORT |
| 3 | Tool-Policy mode-spezifisch | 1-2h | 🥈 Danach |
| 4 | Load-only-expected aktivieren | 1h | 🥈 Danach |
| 5 | Tool-Result-Kürzung | 1h | 🥉 Später |
| 6 | Prompt-Kürzung PLANNER | 2h | 🥉 Später |

**Empfohlene Reihenfolge:** Schritt 1 → messen → Schritt 2 → messen → Schritt 3 → entscheiden.

---

## 13. Akzeptanzkriterien gesamt

- [ ] Token-Verbrauch pro Run reduziert auf < 1,2M (konservativ) bzw. < 800k (optimistisch)
- [ ] Keine Funktionsverluste bei Ingest/Edit-Mode
- [ ] Alle Runs produzieren vollständiges `audit.md` + `audit.json`
- [ ] Turn-Zahlen sind in `audit.md` sichtbar
- [ ] REVIEWER bleibt bei 4 Turns (ONE-PASS)
- [ ] CODER schafft from-scratch Website in max 6 Turns

---

## 14. Referenzen

- **Analyse-Dokument:** `docs/decisions/Stand 23.07.2026_Token_Effizienz_Analyse.md`
- **Architektur-Dokument:** `docs/PiMesh_Architektur.md`
- **Audit-Daten:** `archive/runs/ce5e5edb-cf93-4c3b-a4f1-598275610163/audit.json`
- **Worker-Logs:** `pimesh/**/.pi/work/ce5e5edb-cf93-4c3b-a4f1-598275610163/*/worker.log`

---

## 15. Offene Fragen

| Frage | Status | Entscheidung |
|-------|--------|--------------|
| Soll Turn-Limit v1 als Warnung oder Hard-Fail implementiert werden? | Offen | Empfehlung: Warnung + Audit, Hard-Fail nur für REVIEWER |
| Soll Strategy 2 (Fallback) entfernt oder geflaggt werden? | Offen | Empfehlung: Geflaggt (`FIRMA_REVIEW_LOAD_ALL_ARTIFACTS`) |
| Soll `FIRMA_CODER_TOOLS=write_only` als experimenteller Modus eingeführt werden? | Offen | Empfehlung: Ja, aber nicht als Default |
| Welche Turns sind akzeptabel für CODER from-scratch (3 Dateien)? | Offen | Empfehlung: max 6 Turns |
