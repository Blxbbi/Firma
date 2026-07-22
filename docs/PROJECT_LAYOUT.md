# 🗺️ Projekt-Layout: Firma Engine

Dieses Dokument definiert die strukturelle Organisation der Firma-Plattform. Es dient als Richtlinie, um "Müll-Explosionen" zu verhindern und eine klare Trennung zwischen Code, Zustand und Archiv zu gewährleisten.

## 📂 Verzeichnis-Struktur

```text
/Firma
├── engine/             # KERN: Die Runtime-Logic (Spezifikationen, State-Machine, Orchestrator)
├── workers/            # MUSKELN: Implementierungen der Worker-Rollen (Planner, Executor, etc.)
├── platform/           # ENTRY: Lifecycle-Management und Start-Skripte (z.B. main.py)
├── docs/               # WISSEN: Strategische Dokumente, Tagesberichte, Architektur-Guides
├── tests/              # QUALITÄT: Formale Test-Suites, Adversarial-Tests, Härtungs-Tests
├── benchmarks/         # PERFORMANCE: Telemetrie-Sammler und Benchmarking-Harnesses
├── data/               # ZUSTAND (Ephemer & Persistent)
│   ├── db/             # SQLite Datenbanken (.db)
│   └── artifacts/      # Physische Datei-Outputs der Worker (Run-scoped)
└── archive/            # HISTORIE (Read-Only / Legacy)
    ├── logs/           # Alle System- und Execution-Logs
    ├── legacy_scripts/ # Veraltete Experimente und Debug-Skripte
    └── temp/           # Temporäre Dateien (.csv, .txt) aus Debugging-Sessions
```

## ⚙️ Zustands-Regeln

### 1. Root-Sauberkeit
Das Root-Verzeichnis darf **keine** Runtime-Dateien enthalten. 
- Keine `.db` Dateien im Root.
- Keine `.log` Dateien im Root.
- Keine `run_*.py` Skripte (diese gehören in `archive/legacy_scripts/` oder `platform/`).

### 2. Daten-Isolation (Run-Scoped)
Artefakte werden strikt nach Run isoliert:
`data/artifacts/<run_id>/<task_id>/<filename>`
Dies verhindert Kollisionen bei parallelen Runs.

### 3. Persistenz-Hierarchie
- **Spezifikationen & Code:** Liegen in `engine/` und `workers/` $\rightarrow$ Versioniert via Git.
- **Zustand & Artefakte:** Liegen in `data/` $\rightarrow$ Ignoriert via `.gitignore`.
- **Historie:** Liegt in `archive/` $\rightarrow$ Ignoriert via `.gitignore`.

### 4. Lebenszyklus & Reinigung (Garbage Collection)
Die Plattform implementiert eine Retention-Policy:
- **Standard:** Die letzten 10 Runs werden behalten, ältere werden automatisch gelöscht.
- **Milestones:** Runs mit `is_milestone = True` sind immun gegen die automatische Reinigung und müssen manuell archiviert werden.

---

**Regel:** Wenn du eine Datei im Root erstellst $\rightarrow$ verschiebe sie sofort an den richtigen Ort.
