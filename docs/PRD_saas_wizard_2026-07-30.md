# PRD: Minimaler SaaS-Onboarding-Wizard

## AUFGABE
Baue einen minimalen, dokumentierten SaaS-Onboarding-Wizard als lokale HTML/JS/CSS-Anwendung.

## Kontext
- Zielprodukt ist ein kleines, servierbares HTML/JS/CSS-Endprodukt.
- Es gibt keine Build-Tools, keine Frameworks, keine externen APIs.
- Der Wizard muss lokal im Browser lauffähig sein.

## Spezifikation

### Schritt 1: Begrüßung + Dateneingabe
- **Dateien:** index.html, style.css
- **Felder:** Name, E-Mail, Unternehmensgröße
- **Anforderung:** Eingaben werden clientseitig validiert; Fehler müssen sichtbar sein.

### Schritt 2: Profilauswahl
- **Datei:** app.js
- **Auswahl zwischen 3 Profilen:** Admin, Manager, Viewer
- **Anforderung:** Auswahl wird im UI gespeichert und im nächsten Schritt vorausgewählt.

### Schritt 3: Zusammenfassung
- **Dateien:** index.html, style.css, app.js
- **Anforderung:** Zeigt alle vorherigen Eingaben übersichtlich an.
- **Besondere Regel:** Es darf KEINE neuen Dateien außer index.html, style.css, app.js geben.
- **Besondere Regel:** Es darf KEIN fetch(), KEIN localStorage-API, KEIN sessionStorage und KEIN externes CDN verwendet werden.

### Schritt 4: Abschluss
- **Datei:** index.html
- **Anforderung:** Zeigt eine Dankesseite mit der exakten Zusammenfassung aus Schritt 3.
- **Besondere Regel:** Keine neuen Dateien; nur Änderungen in index.html erlaubt.

## Akzeptanzkriterien
- Öffnet index.html direkt im Browser und funktioniert ohne Server.
- Alle 3 Schritte sind navigierbar vorwärts und rückwärts.
- Validierung blockiert Weiter bei fehlenden Feldern.
- Keine erlaubte Technologie aus Schritt 3/4 wird verwendet.
- Keine unerwarteten Dateien im Endprodukt.

## Besondere Prüfung
- Beschwere dich nicht in Freitext-Ausgaben.
- Wenn etwas nicht möglich ist, markiere es als BLOCKED mit technischem Grund.
- Halte jede Aufgabe unter 3 zu erstellenden/ändernden Dateien.
