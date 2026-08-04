# Statusbericht: Adaptive Planner-Integration für den Firma-Workflow

**Datum:** 25.07.2026  
**Autor:** Arthur (mit Pi-Coding-Agent)  
**Betreff:** Erweiterung des Firma-Frameworks von starrem 3-Task-System zu intelligentem, adaptiven Workflow  
**Status:** Entwurf / Review-fähig

---

## 1. Executive Summary

Das Firma-Framework hat eine solide Infrastruktur (Worker-Spawn, Scheduler, Gate, Baseline, Review). Aktuell ist es jedoch auf **starre 3-Task-Pläne** festgelegt, die für einfache Websites funktionieren, aber bei komplexeren Projekten oder iterativen Änderungen an Grenzen stoßen.

**Ziel dieser Erweiterung:** Den Planner von einem "Übersetzer vordefinierter Tasks" zu einem **intelligenten Architekten** machen, der selbstständig analysiert, plant und die passende Anzahl an Tasks erstellt.

---

## 2. Vision: Was Firma eigentlich leisten soll

Firma soll kein Website-Baukasten sein, sondern ein **generischer Multi-Agenten-Workflow**, der:

### 2.1 Kernprinzipien

1. **Agenten sind austauschbar** → Researcher, Planner, Coder, Reviewer sollen ein- und aushängbar sein
2. **Anfrage-getriebene Planung** → Der Planner analysiert die User-Anfrage und entscheidet selbst, was gebaut werden muss
3. **Adaptive Komplexität** → Einfache Änderungen = 1 Task, komplexe Projekte = 5+ Tasks
4. **Iterative Bearbeitung** → "Ändere X am bestehenden System" funktioniert genauso wie "Baue etwas Neues"

### 2.2 Beispiel-Workflow (Zielzustand)

**User-Anfrage:** *"Füge zu jedem Worker in der Architektur-Sektion eine Click-Funktion hinzu, die Details anzeigt."*

**Ablauf:**
```
1. RESEARCHER (optional):
   - Liest aktuelle index.html
   - Identifiziert: "6 Worker-Cards mit Klasse .worker-card, keine Event-Listener"
   - Gibt Kontext an Planner: "Delta = Click-Handler für bestehende Elemente"

2. PLANNER (intelligent):
   - Analysiert: "Das ist eine kleine Erweiterung, kein Redesign"
   - Entscheidet: "Braucht nur 1 Task — app.js erweitern"
   - Erstellt Task:
     * Scope: nur app.js
     * Beschreibung: "Event-Listener zu .worker-card hinzufügen"
     * Akzeptanzkriterien: "CONTAINS:app.js:worker-card", "CONTAINS:app.js:addEventListener"

3. CODER:
   - Bekommt präzisen 1-Task-Auftrag
   - Implementiert nur die Änderung

4. REVIEWER:
   - Prüft, ob Click-Funktion korrekt implementiert ist
   - Prüft, keine Seiteneffekte entstanden sind
```

---

## 3. Problem-Analyse: Warum das aktuelle System nicht funktioniert

### 3.1 Der Planner ist kein Planer, sondern ein Übersetzer

**Aktueller Ablauf:**
```
User-Anfrage → Researcher (schreibt Brief) → Planner (übersetzt in 3 Tasks) → Coder → Reviewer
```

**Das Problem:**
- Der Researcher schreibt **fast die ganze Lösung vor** (Dateien, Technologien, Struktur)
- Der Planner bekommt **vordefinierte Akzeptanzkriterien**: `EXISTS:index.html`, `EXISTS:style.css`, `EXISTS:app.js`
- Der Planner hat **keinen Entscheidungsspielraum** — er kann nur "übersetzen", nicht "denken"

### 3.2 Beispiel: Karten-App mit Zeichenfunktion

**User-Anfrage:** *"Ich will eine App, wo eine Karte von Maps angezeigt wird, man darauf zeichnen kann und Gebiete markieren kann wie in Paint, die dann gespeichert werden."*

**Was der aktuelle Planner tun würde:**
```
task-1: index.html (Karte + Canvas)
task-2: style.css (Styling)
task-3: app.js (alles in einer Datei)
```

**Was ein intelligenter Planner tun sollte:**
```
Analyse: "Das ist eine komplexe App mit mehreren Features"
Plan:
  - task-1: Basis-Karte integrieren (Leaflet/Mapbox)
  - task-2: Zeichen-Tools (Pins, Polygone, Freihand)
  - task-3: State-Management für gezeichnete Gebiete
  - task-4: Speichern/Laden (LocalStorage + Datei-Export)
  - task-5: UI für Werkzeug-Auswahl
```

**Warum das aktuell nicht funktioniert:**
- Der Researcher schreibt schon vor: "Plain HTML/CSS/JS, keine Frameworks"
- Der Planner bekommt die Akzeptanzkriterien vordefiniert: `EXISTS:index.html`, `EXISTS:style.css`, `EXISTS:app.js`
- Der Planner kann nicht entscheiden: "Das braucht 5 Tasks und vielleicht eine Library"

### 3.3 Keine Delta-Planung für Änderungen

**Aktuell:** Jeder Run ist ein Greenfield-Projekt (von Null an)  
**Problem:** *"Ändere X an der Website"* → funktioniert nicht gut, weil der Planner nicht erkennt, was geändert werden muss

---

## 4. Lösungsarchitektur: Schritt-für-Schritt

### Phase 1: Planner-Prompt liberalisieren (1-2 Tage)

**Ziel:** Planner bekommt Spielraum, selbst zu entscheiden

**Änderungen:**
1. **Prompt anpassen:**
   ```
   ALT: "Du erstellst EINEN Plan (plan_draft). Schreibe KEINEN Code."
   NEU: "Analysiere die Anfrage und den Projekt-Kontext. 
         Entscheide selbst:
         - Wie viele Tasks werden gebraucht?
         - Welche Dateien müssen geändert werden?
         - Welche Reihenfolge ist sinnvoll?"
   ```

2. **Akzeptanzkriterien dynamisch machen:**
   - Statt vordefinierter `EXISTS:index.html` etc.
   - Planner definiert selbst: *"CODER muss index.html um Header erweitern"*

3. **Task-Zahl entkoppeln:**
   - Entferne `_snake_config()` (hardcoded 3 Tasks)
   - Entferne `_expand_plan_to_5_tasks()` (Test-Hook)
   - Planner entscheidet: 1, 3, 5, 10 Tasks — je nach Komplexität

**Test-Case:**
- User-Anfrage: *"Füge Click-Funktionen zu Architektur-Workern hinzu"*
- Erwartung: Planner erstellt **1 Task** (nur app.js erweitern)
- Erfolgskriterium: Task hat Scope `app.js`, nicht 3 Tasks

---

### Phase 2: Researcher auf "Kontext-Lieferant" reduzieren (1 Tag)

**Ziel:** Researcher gibt nur Kontext, keine Lösung vor

**Änderungen:**
1. **Prompt anpassen:**
   ```
   ALT: "Erstelle eine professionelle Website mit..."
   NEU: "Analysiere den Projektstand. Was existiert? Was fehlt? Gib dem Planner Kontext."
   ```

2. **Brief-Struktur ändern:**
   ```markdown
   ## User Goal
   <Was der User will>
   
   ## Current State
   <Was existiert bereits (Dateien, Struktur)>
   
   ## Gap Analysis
   <Was fehlt, um das Ziel zu erreichen>
   
   ## Recommendations
   <Konkrete Vorschläge, aber KEINE Lösung>
   ```

3. **Keine Datei-Vorgaben mehr:**
   - Researcher sagt nicht mehr: "Es müssen index.html, style.css, app.js entstehen"
   - Researcher sagt: "Das Projekt hat diese Dateien, das fehlt..."

**Test-Case:**
- User-Anfrage: *"Mach eine Karten-App"*
- Erwartung: Researcher erkennt "keine existing files", empfiehlt Leaflet/Mapbox
- **Aber:** Researcher sagt NICHT: "Erstelle index.html, style.css, app.js"

---

### Phase 3: Delta-Planung für iterative Änderungen (2-3 Tage)

**Ziel:** *"Ändere X am bestehenden System"* funktioniert

**Änderungen:**
1. **Ingest-Mode erweitern:**
   - Aktuell: `setup_ingest_run()` staged Projekt für Greenfield
   - Neu: `setup_delta_run()` staged Projekt + identifiziert Delta

2. **Researcher bekommt "Diff-Auftrag":**
   ```
   "Lies den aktuellen Stand. Was muss geändert werden, um [User-Anfrage] zu erfüllen?"
   ```

3. **Planner plant nur das Delta:**
   - Nicht: "Erstelle die ganze Website neu"
   - Sondern: "Erweitere app.js um Click-Handler für .worker-card"

**Test-Case:**
1. Run 1: Baue Firma-Website (wie bisher)
2. Run 2: *"Füge Click-Funktionen zu Architektur-Workern hinzu"*
3. Erwartung: Run 2 ändert nur app.js, nicht index.html/style.css

---

### Phase 4: Adaptive Task-Zahl und Priorisierung (2-3 Tage)

**Ziel:** Planner priorisiert Features und entscheidet Task-Zahl

**Änderungen:**
1. **Komplexitäts-Analyse im Planner:**
   ```python
   # Pseudocode im Planner-Prompt
   if anfrage_hat_viele_features():
       tasks = 5-7
       priorisiere("MVP zuerst")
   elif anfrage_ist_kleine_aenderung():
       tasks = 1
   else:
       tasks = 3
   ```

2. **Priorisierungs-Logik:**
   - Planner erstellt **Backup-Tasks** für nice-to-have Features
   - Core-Features = Task 1, 2, 3
   - Nice-to-have = Task 4, 5 (werden nur ausgeführt, wenn Zeit bleibt)

**Test-Case:**
- User-Anfrage: *"Mach eine Karten-App mit Zeichnen, Speichern, Laden und Werkzeug-Auswahl"*
- Erwartung: 
  - Task 1: Basis-Karte (MVP)
  - Task 2: Zeichen-Tools (MVP)
  - Task 3: Speichern/Laden (MVP)
  - Task 4: Werkzeug-Auswahl (nice-to-have)
  - Task 5: UI-Polishing (nice-to-have)

---

## 5. Was wir sonst noch brauchen

### 5.1 Technische Komponenten

| Komponente | Status | Aufwand |
|------------|--------|---------|
| **Planner-Prompt liberalisieren** | 🟢 Einfach | 1-2 Stunden |
| **Researcher-Prompt anpassen** | 🟢 Einfach | 1 Stunde |
| **Dynamische Task-Zahl** | 🟡 Mittel | 2-3 Stunden |
| **Delta-Planung (Ingest-Mode)** | 🟡 Mittel | 3-4 Stunden |
| **Komplexitäts-Analyse** | 🟡 Mittel | 2-3 Stunden |
| **Test-Suite für adaptive Planung** | 🔴 Aufwändig | 1-2 Tage |
| **Gesamt** | | **~3-4 Tage** |

### 5.2 Prompt-Engineering

**Benötigte Skills:**
- Prompt-Design für "Analyse vs. Lösung"
- Kontext-führende Prompts (aktuellen Stand lesen, Delta erkennen)
- Entscheidungs-Prompts (Wie viele Tasks? Welche Priorität?)

**Ressourcen:**
- Pi-Coding-Agent (mich) für Prompt-Entwicklung
- Test-Cases mit verschiedenen Projekt-Typen (Website, App, Spiel)

### 5.3 Testing-Strategie

**Deterministische Tests:**
1. **Unit-Tests für Planner-Entscheidungen:**
   - Einfache Änderung → 1 Task
   - Neues Feature → 3 Tasks
   - Komplexe App → 5+ Tasks

2. **Integration-Tests:**
   - Run 1: Baue Projekt
   - Run 2: Ändere Projekt (Delta-Test)
   - Run 3: Ändere Projekt wieder (Iterations-Test)

3. **Regression-Tests:**
   - Alte 3-Task-Runs funktionieren noch
   - Gate-Serialisierung funktioniert bei 1, 3, 5, 10 Tasks

---

## 6. Risiken und Herausforderungen

### 6.1 Technische Risiken

| Risiko | Wahrscheinlichkeit | Auswirkung | Mitigation |
|--------|-------------------|------------|------------|
| **Planner übertreibt** (zu viele Tasks) | Mittel | Token-Kosten steigen | Max-Task-Limit (z.B. 10) + Review-Schleife |
| **Planner unterschätzt** (zu wenige Tasks) | Mittel | Unvollständige Umsetzung | Review-Checker prüft Akzeptanzkriterien |
| **Researcher zu viel Freiheit** | Niedrig | Inkonsistente Briefe | Template für Brief-Struktur |
| **Delta-Planung erkennt Änderung nicht** | Mittel | Coder baut falsch | Researcher muss Delta klar beschreiben |

### 6.2 Konzeptuelle Herausforderungen

1. **"Intelligenz" ist Prompt-Limitiert:**
   - Der Planner kann nur so gut sein wie das Prompt-Design
   - Komplexe Architekturentscheidungen (z.B. "Soll ich React oder Vanilla JS nehmen?") muss der Planner selbst treffen — das erfordert gute Prompts

2. **Token-Kosten:**
   - Mehr Analyse im Researcher/Planner = mehr Tokens
   - Delta-Planung erfordert Lesen des aktuellen Stands = mehr Input-Tokens

3. **Debugging:**
   - Wenn Planner falsch entscheidet, ist es schwerer zu debuggen als bei festen 3 Tasks
   - Braucht bessere Logging-Strategie

---

## 7. Empfehlung

### 7.1 Kurzfristig (diese Woche)

**Priorität 1: Planner-Prompt liberalisieren**
- Prompt so umschreiben, dass Planner selbst entscheidet
- Test-Case: *"Füge Click-Funktionen hinzu"* → sollte 1 Task werden
- Aufwand: 1-2 Stunden
- Risiko: Niedrig

**Priorität 2: Researcher auf Konzept reduzieren**
- Prompt anpassen, keine Datei-Vorgaben mehr
- Test-Case: *"Mach eine Karten-App"* → Researcher empfiehlt Stack, aber schreibt keine Lösung vor
- Aufwand: 1 Stunde
- Risiko: Niedrig

### 7.2 Mittelfristig (nächste 1-2 Wochen)

**Delta-Planung implementieren:**
- Erweitere Ingest-Mode für "Änderung an bestehendem Projekt"
- Test-Case: Website bauen → Click-Funktion hinzufügen
- Aufwand: 3-4 Stunden
- Risiko: Mittel

**Adaptive Task-Zahl:**
- Planner bekommt Komplexitäts-Analyse
- Test-Case: Einfache Änderung (1 Task) vs. komplexe App (5+ Tasks)
- Aufwand: 2-3 Stunden
- Risiko: Mittel

### 7.3 Langfristig (nächster Monat)

**Vollständige Agenten-Austauschbarkeit:**
- Module für Researcher, Planner, Coder, Reviewer
- Konfigurationsdatei: `agents.yaml` (welche Agenten aktiv, welche Modelle)
- Test-Case: Workflow mit nur Coder+Reviewer (kein Researcher/Planner) für einfache Tasks

---

## 8. Offene Fragen

1. **Soll der Planner immer den aktuellen Stand lesen?**
   - Pro: Bessere Delta-Erkennung
   - Contra: Mehr Tokens, langsamer
   - **Vorschlag:** Ja, aber mit Token-Limit (z.B. nur erste 1000 Zeilen pro Datei)

2. **Soll es einen "Planner-Review" geben?**
   - Pro: Verhindert Over-Engineering (zu viele Tasks)
   - Contra: Noch ein Agent, noch mehr Tokens
   - **Vorschlag:** Nein, stattdessen Max-Task-Limit (z.B. 10 Tasks)

3. **Wie testen wir deterministisch?**
   - Pro: Klare Test-Cases mit erwarteter Task-Zahl
   - Contra: LLM ist nicht 100% deterministisch
   - **Vorschlag:** "Wahrscheinlichkeits-Tests" (z.B. "In 80% der Fälle sollte 1 Task erstellt werden")

---

## 9. Nächste Schritte

1. **Review dieses Berichts** mit dem Berater
2. **Priorisierung festlegen:** Was zuerst? (Planner-Prompt? Delta-Planung?)
3. **Prompt-Entwicklung:** Umsetzung der Änderungen in `engine/services/plan_instantiator.py` und Worker-Prompts
4. **Test-Cases definieren:** Konkrete User-Anfragen zum Testen
5. **Iterative Verbesserung:** Nach jedem Test-Case anpassen

---

## 10. Fazit

Das Firma-Framework hat eine **solide Basis**, die nur **prompt-seitig** erweitert werden muss. Die Vision ist realistisch und mit überschaubarem Aufwand umsetzbar.

Der größte Gewinn: **Firma wird von einem Website-Baukasten zu einem generischen Agenten-Workflow**, der echte Probleme lösen kann — nicht nur "baue mir eine Homepage", sondern "analysiere mein Problem, plane die Lösung, führe sie aus".

**Empfehlung:** Sofort mit **Phase 1** starten (Planner-Prompt liberalisieren), dann iterativ testen und verbessern.

---

*Bericht erstellt am 25.07.2026*
