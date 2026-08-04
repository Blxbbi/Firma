# PRD: Complex SaaS Onboarding Wizard "AcmeLaunch"

## Goal
Erstelle eine vollständige SaaS-Onboarding-Plattform "AcmeLaunch" als 4-geteilten Wizard mit klaren Dateiverantwortlichkeiten über Tasks hinweg.

## Requirements

### Task 1 - Foundation (CREATE)
- **CREATE** `index.html`: Komplettes HTML-Grundgerüst mit Navigation, 4 Step-Containern (Step-1, Step-2, Step-3, Step-4), Footer
- **CREATE** `style.css`: Alle Basis-Styles, CSS-Variablen (Farben, Spacing), Reset, Grid-Layout, Navigation-Styles
- **CREATE** `app.js`: State-Management (currentStep, userData), Router-Funktionen, Event-System, Utility-Funktionen

### Task 2 - Step 1+2 Implementation (UPDATE)
- **UPDATE** `index.html`: Fülle Step-1-Container mit Welcome-Screen (Logo, Headline, Beschreibung, Next-Button) und Step-2-Container mit Feature-Liste (Checkboxen für 5 Features)
- **UPDATE** `style.css`: Ergänze Step-1-spezifische Styles (Logo-Animation, Toggle-Styles) und Step-2-spezifische Styles (Checkbox-Design, Hover-Effekte)
- **UPDATE** `app.js`: Ergänze Step-1-Logik (Toggle-Handler, Welcome-Animation) und Step-2-Logik (Feature-Auswahl, Validation, State-Update)

### Task 3 - Step 3 Implementation (UPDATE)
- **UPDATE** `index.html`: Fülle Step-3-Container mit Pricing-Übersicht (3 Pläne: Basic/Pro/Enterprise, Feature-Vergleichstabelle, Select-Buttons)
- **UPDATE** `style.css`: Ergänze Step-3-spezifische Styles (Pricing-Cards, Highlight-Effekte, Responsive-Tabelle)
- **UPDATE** `app.js`: Ergänze Step-3-Logik (Plan-Selection, Preis-Berechnung, Upgrade-Handler)

### Task 4 - Finalization (UPDATE)
- **UPDATE** `index.html`: Fülle Step-4-Container mit Summary (Zusammenfassung aller Eingaben), Success-Message, Restart-Button, Footer-Ergänzungen
- **UPDATE** `style.css`: Ergänze Step-4-spezifische Styles (Summary-Box, Success-Icon, Print-Styles für Summary)
- **UPDATE** `app.js`: Ergänze Final-Logik (Summary-Generierung, Formular-Submit, Analytics-Tracking, Restart-Funktion)

## Constraints
- **DATEI-OWNERSHIP**: Jede Datei wird genau einmal CREATEd (Task 1) und mehrfach UPDATEd (Tasks 2-4)
- **CREATE vs UPDATE**: Der Planner MUSS zwischen CREATE (neue Datei) und UPDATE (bestehende Datei erweitern) unterscheiden
- **MAX 3 ARTIFACTS**: Jeder CODER-Task hat maximal 3 expected_artifacts
- **KEINE CROSS-TASK-CREATES**: Nur Task 1 darf Dateien CREATEn, Tasks 2-4 dürfen nur UPDATEn
- **PHASEN-ABHÄNGIGKEIT**: Task 2 basiert auf Task 1 Output, Task 3 basiert auf Task 2 Output, Task 4 basiert auf Task 3 Output

## Acceptance Criteria
1. Alle 4 Tasks werden ohne Ownership-Konflikt akzeptiert
2. CODER erstellt in Task 1 genau 3 Dateien (index.html, style.css, app.js)
3. CODER erweitert in Tasks 2-4 nur die bereits existierenden Dateien (keine neuen Dateien)
4. Der finale Wizard hat funktionierende Navigation zwischen allen 4 Steps
5. Alle States und Eingaben werden über die Steps hinweg beibehalten
6. Der Summary-Step (Task 4) zeigt alle gesammelten Daten korrekt an

## Test Strategy
Dieser Test prüft:
- [x] CREATE/UPDATE-Unterscheidung im Planner
- [x] Multi-Task-Datei-Verkettung (Update ohne Create = Fehler)
- [x] Inkrementelle Erweiterung (CODER edited nur Task-Scope)
- [x] Ownership-Regel: Ein CREATE pro Datei, beliebig viele UPDATEs
