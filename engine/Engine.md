# ⚙️ Engine - Deterministic AI Execution Engine

Dieses Modul bildet das Herzstück der AI-Execution-Engine. Es ist dafür verantwortlich, dass jede Nachricht, die das System erreicht, deterministisch geprüft, validiert und verarbeitet wird.

## 📁 Struktur-Übersicht

Die Engine ist modular aufgebaut, um eine strikte Trennung zwischen Datenstrukturen, Validierungslogik und Prozesssteuerung zu gewährleisten.

```text
engine/
├── models.py    # Datenmodelle (Strukturen)
├── guards.py    # Validierungslogik (Die "Gesetze")
└── workflow.py  # Orchestrierung & Ausführung
```

---

## 📄 Dateibeschreibungen

### 1. `models.py`
**Zweck:** Definition der Datentypen.
Hier werden Pydantic-Modelle verwendet, um eine strikte Typisierung der Nachrichten zu garantieren.
- **`MessageHeader`**: Enthält Metadaten wie `message_id` (für Idempotenz), `sender`, `recipient` und den `message_type`.
- **`Message`**: Die Gesamteinheit aus Header und einem flexiblen Payload.
- **`GuardResult`**: Ein standardisiertes Ergebnisobjekt, das angibt, ob eine Prüfung bestanden wurde (`passed`) oder warum sie fehlgeschlagen ist (`error_code`, `reason`).

### 2. `guards.py`
**Zweck:** Implementierung der deterministischen Prüfregeln.
Dies ist die "Rechtsabteilung" der Engine. Hier wird festgelegt, was erlaubt ist und was nicht.
- **`MessageGuards`**: Eine Klasse mit statischen Methoden für die Validierung.
- **`VALID_TRANSITIONS`**: Eine State-Matrix, die exakt definiert, welcher Zustandsübergang bei welchem Event erlaubt ist (z.B. `READY` $\rightarrow$ `PROCESSING`).
- **`guard_idempotency`**: Verhindert die Mehrfachverarbeitung derselben Nachricht.
- **`guard_state_consistency`**: Stellt sicher, dass die Geschäftslogik (Zustände) nicht verletzt wird.

### 3. `workflow.py`
**Zweck:** Orchestrierung der Guard-Kette.
Hier wird die Logik implementiert, wie eine Nachricht durch die verschiedenen Guards geschleust wird.
- **`process_message_workflow`**: Die Hauptfunktion, die die Guards in der korrekten Reihenfolge aufruft. Wenn ein Guard eine Nachricht ablehnt, wird die Verarbeitung sofort abgebrochen.
- **Test-Szenarien**: Enthält integrierte Tests, um die Korrektheit der State-Transitions zu beweisen.

---

## 🔄 Prozess-Ablauf (Data Flow)

Der Weg einer Nachricht durch die Engine sieht wie folgt aus:

`Eingang` $\rightarrow$ **`workflow.py`** $\rightarrow$ **`guards.py`** (Idempotenz $\rightarrow$ State) $\rightarrow$ **`models.py`** (Typ-Check) $\rightarrow$ `Ergebnis/Ausführung`

### Kernprinzipien dieser Implementierung:
1. **Determinismus**: Gleicher Input + gleicher Zustand = immer gleiches Ergebnis.
2. **Trust-Zero**: Keine Nachricht wird ohne Validierung durch die Guards verarbeitet.
3. **Fail-Fast**: Sobald eine Regel verletzt wird, bricht das System die Verarbeitung ab.
