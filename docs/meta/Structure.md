# 🏗️ Projekt-Struktur: Firma AI-Execution-Runtime

Dieses Dokument beschreibt die anatomische Struktur des Firma-Projekts. Die Architektur folgt dem Prinzip der **striktem Trennung von Zustandssteuerung, Logik-Ausführung und Daten-Persistenz**.

## 🗺️ High-Level Map

```text
/Firma
├── engine/             # 🧠 Der Kern (The Brain)
├── workers/            # 💪 Die Ausführung (The Muscles)
├── platform/           # 🕹️ Die Steuerung (The Supervisor)
├── docs/               # 📚 Das Wissen (The Memory)
├── tests/              # 🛡️ Die Qualität (The Guard)
├── benchmarks/         # ⏱️ Die Messung (The Telemetry)
├── data/               # 💾 Der Zustand (The State)
└── archive/            # 📦 Die Historie (The Archive)
```

---

## 📂 Detaillierte Ordner-Analyse

### 1. `/engine` (The Core Runtime)
**Zweck:** Hier liegt die "Wahrheit" des Systems. Die Engine ist LLM-agnostisch; sie kümmert sich nur um den deterministischen Prozess.
- **Inhalt:** 
    - `controller.py`: Lifecycle-Management der Runs.
    - `orchestrator.py`: Steuerung der Task-Sequenzen.
    - `scheduler.py`: Zuweisung von Tasks an Worker.
    - `repository.py` & `db.py`: Datenzugriff und Persistenz-Logik.
    - `services/`: Spezialisierte Logik wie `artifact_store.py` oder `verification_service.py`.
- **Herkunft:** Entstanden aus der Notwendigkeit, probabilistische LLMs in eine deterministische State-Machine zu zwingen.

### 2. `/workers` (The LLM Implementation)
**Zweck:** Die Schnittstelle zur KI. Hier wird definiert, *wie* eine Rolle (Planner, Coder etc.) arbeitet.
- **Inhalt:**
    - `planner.py`: Logik zur Transformation von User-Zielen in Task-Listen.
    - `executor.py`: Logik zur Generierung von Code/Artefakten.
    - `llm_worker.py`: Basis-Klasse für die Provider-Kommunikation.
- **Herkunft:** Die "Muskeln" des Systems. Diese Dateien ändern sich oft, wenn Prompts oder Modelle optimiert werden.

### 3. `/platform` (The Supervisor Layer)
**Zweck:** Der Einstiegspunkt. Die Platform-Schicht verbindet die Engine mit einer konkreten Aufgabe (z.B. Website-Bau).
- **Inhalt:**
    - `main.py`: Der zentrale Startpunkt für die Execution eines Projekts.
- **Herkunft:** Evolution von einfachen Test-Skripten hin zu einem kontrollierten Entry-Point.

### 4. `/docs` (The Project Memory)
**Zweck:** Dokumentation der Vision, der Fortschritte und der Architektur-Entscheidungen.
- **Inhalt:**
    - `Firma.md`: Das strategische Manifest.
    - `Stand_*.md`: Tägliche Fortschrittsberichte und Meilensteine.
    - `Structure.md`: Diese Datei.
- **Herkunft:** Dokumentation der "Reise" von der Idee zur Plattform.

### 5. `/tests` (Quality Assurance)
**Zweck:** Sicherstellen, dass neue Features keine Regressionen verursachen.
- **Inhalt:**
    - `adversarial/`: Stress-Tests für Race-Conditions.
    - `test_industrial_isolation.py`: Verifizierung der `run_id`-Trennung.
- **Herkunft:** Entstanden aus den Schmerzen der "Silent Hangs" und "Zombie-Tasks".

### 6. `/benchmarks` (Performance & Telemetry)
**Zweck:** Messung der Effizienz der Provider und der Engine.
- **Inhalt:**
    - `collector.py`, `evaluator.py`: Tools zur Analyse von Latenz und Erfolgsraten.
    - `results/`: Historische Performance-Daten.
- **Herkunft:** Notwendigkeit, die "Kognitive Schwelle" (z.B. 8B vs 70B) objektiv zu messen.

### 7. `/data` (State & Persistence)
**Zweck:** Alle dynamisch erzeugten Daten. Dieser Ordner ist ephemer (wird via `.gitignore` ausgeschlossen).
- **Inhalt:**
    - `db/`: SQLite-Dateien der Runs (`platform_industrial.db`).
    - `artifacts/`: Physische Dateien, die von Workern erstellt wurden (`<run_id>/<task_id>/`).
- **Herkunft:** Trennung von Code (statisch) und Zustand (dynamisch).

### 8. `/archive` (The History)
**Zweck:** Ablage für alles, was nicht mehr aktiv genutzt wird, aber für die Forensik wichtig ist.
- **Inhalt:**
    - `logs/`: Historische Ausführungs-Logs.
    - `legacy_scripts/`: Alte `run_*.py` Experimente.
    - `temp/`: Debugging-Fragmente (`.csv`, `.txt`).
- **Herkunft:** Ergebnis der "Operation Tabula Rasa" zur Vermeidung von Root-Verschmutzung.

---

## 🛠️ Der Lebenszyklus einer Datei

| Dateityp | Zielort | Status |
| :--- | :--- | :--- |
| Neuer Engine-Feature | `engine/services/` | Git-tracked |
| Neuer Worker-Prompt | `workers/` | Git-tracked |
| Neuer Test-Case | `tests/` | Git-tracked |
| Run-Datenbank | `data/db/` | `.gitignore` |
| Generierter Code | `data/artifacts/` | `.gitignore` |
| Debug-Log | `archive/logs/` | `.gitignore` |
| Altes Experiment-Skript | `archive/legacy_scripts/` | Git-tracked (optional) |

---

**Regel:** Wenn eine Datei nicht in dieses Schema passt, muss sie entweder in das `archive/` oder die Struktur muss erweitert werden. **Keine Dateien im Root-Verzeichnis.**
