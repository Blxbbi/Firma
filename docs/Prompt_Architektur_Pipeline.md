# Prompt-Architektur & Pipeline
**Stand:** 2026-07-29  
**Zweck:** Zentrale Prompt-Verwaltung, Nachvollziehbarkeit, Token-Optimierung

---

## 📊 Übersicht: So fließen die Prompts

```
┌─────────────────────────────────────────────────────────────────────┐
│  1. START: run_pi_mesh.py / run_snake.py                           │
│     - Lädt Run-Konfiguration                                       │
│     - Startet Engine                                               │
└────────────────────────────┬────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  2. ENGINE: orchestrator.py / scheduler.py                         │
│     - Holt project_prompt aus run.config_json["prompt"]            │
│     - Teilt Run in Tasks auf                                       │
│     - Weißt Tasks Rollen zu: PLANNER, RESEARCHER, CODER, REVIEWER  │
└────────────────────────────┬────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  3. WORKER START: provider.spawn()                                 │
│     - Erstellt worker.log + prompt.txt                             │
│     - prompt.txt sagt: "Lies task-X.md und befolge Anweisungen"    │
└────────────────────────────┬────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  4. TASK-SPEC GENERIERUNG: pi_mesh_transport.py                    │
│     - Schreibt task-X.md basierend auf:                            │
│       • Assignment-JSON (run_id, task_id, role, etc.)              │
│       • PromptLoader.load_contract('reviewer_output')              │
│       • PromptLoader.load_contract('coder_output')                 │
│       • Akzeptanzkriterien                                         │
│     - Datei: pimesh/<crew>/.pi/messenger/crew/tasks/task-X.md     │
└────────────────────────────┬────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  5. WORKER LÄDT PROMPT:                                            │
│     - Worker startet pi --mode json                                │
│     - Liest prompt.txt → "Lies task-X.md"                         │
│     - Liest task-X.md → volle Spezifikation                       │
│     - Führt Aufgabe aus                                            │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 📁 Prompt-Repository Struktur

```
prompts/
├── contracts/                  # PiMesh Output Contracts
│   ├── planner_output.md       # → task-X.md für PLANNER
│   ├── coder_output.md         # → task-X.md für CODER
│   ├── reviewer_output.md      # → task-X.md für REVIEWER
│   └── researcher_output.md    # → task-X.md für RESEARCHER
│
├── planner/
│   ├── system.md               # In-Process System Prompt
│   ├── user_template.md        # In-Process User Prompt
│   └── pimesh_research_context.md  # Scheduler-Injektion
│
├── executor/
│   ├── system.md               # In-Process System Prompt
│   └── user_template.md        # In-Process User Prompt Template
│
├── researcher/
│   ├── system.md               # In-Process System Prompt
│   └── user_template.md        # In-Process User Prompt Template
│
└── reviewer/
    └── pimesh_system.md        # PiMesh Reviewer Prompt (Header)
```

---

## 🔑 Die 6 Ladepfade im Überblick

| Pfad | Wann | Wo geladen | Aus welcher Datei |
|------|------|------------|-------------------|
| **1. In-Process System** | Worker startet direkt | `workers/*.py` | `prompts/<role>/system.md` |
| **2. In-Process User** | Worker erstellt User-Prompt | `workers/*.py` | `prompts/<role>/user_template.md` |
| **3. PiMesh Contract** | task-X.md wird generiert | `pi_mesh_transport.py` | `prompts/contracts/<role>_output.md` |
| **4. Scheduler Injektion** | PLANNER Assignment gebaut | `scheduler.py` | `prompts/planner/pimesh_research_context.md` |
| **5. PiMesh System** | task-X.md Header gebaut | `pi_mesh_transport.py` | `prompts/<role>/pimesh_system.md` |
| **6. Review-Code-Blocks** | Bisher NOCH aus pi_mesh_transport.py | `pi_mesh_transport.py:350` | Direkt aus review_artifacts |

---

## ⚠️ Was NOCH hardcoded ist

| Element | Datei | Warum |
|---------|-------|-------|
| **Review-Code-Blöcke** | `pi_mesh_transport.py:350-358` | Wird dynamisch aus CODER-Output generiert |
| **Assignment-JSON** | `pi_mesh_transport.py:270-280` | Task-spezifische Daten (run_id, task_id, etc.) |
| **Akzeptanzkriterien** | `scheduler.py` + `pi_mesh_transport.py` | Kommen aus DB/Task-Definition |

---

## 🆚 Vorher vs. Nachher

### Vorher:
```
Worker startet → hardcoded Prompt → LLM
```

### Nachher:
```
Worker startet → PromptLoader.load() → prompts/ Datei → LLM
```

### Vorteile:
| Vorteil | Erklärung |
|---------|-----------|
| **Single Source of Truth** | Alle Prompts an einem Ort |
| **Kein Code-Deployment** | Prompt-Änderungen ohne Code-Änderung |
| **A/B-Testing möglich** | Einfach Varianten testen |
| **Prompt-Performance tracken** | Metriken pro Prompt möglich |
| **Reviewer-Logik zentral** | Nicht mehr verstreut in Transport/Contracts |

---

## 📈 PromptLoader API

### Laden von Role-spezifischen Prompts:
```python
from engine.prompt_loader import get_prompt_loader

loader = get_prompt_loader()

# In-Process Prompts
planner_system = loader.load('planner', 'system')
executor_system = loader.load('executor', 'system')
researcher_system = loader.load('researcher', 'system')

# PiMesh Prompts
planner_pimesh = loader.load('planner', 'pimesh_system')
executor_pimesh = loader.load('executor', 'pimesh_system')
```

### Laden von Contracts:
```python
reviewer_contract = loader.load_contract('reviewer_output')
coder_contract = loader.load_contract('coder_output')
```

---

## 🚀 Nächste Schritte

1. **Review-Code-Blöcke aus PiMeshTransport entfernen** → Worker lesen Dateien selbst
2. **Assignment-JSON zentralisieren** → Prompt Template statt String-Konkatenation
3. **Akzeptanzkriterien aus DB direkt in task-X.md** → Weniger Injektionen
4. **Prompt-Performance-Tracking** → Welche Prompts führen zu welchen Tokens?

---

## 📚 Verwandte Dokumente

- [PiMesh_Architektur.md](PiMesh_Architektur.md) — Gesamtsystem-Architektur
- [docs/briefings/Statusbericht_Retry_Provider_Tokenverbrauch_2026-07-26.md](docs/briefings/Statusbericht_Retry_Provider_Tokenverbrauch_2026-07-26.md) — Token-Analyse
- [docs/Token_Optimierungs_Plan_2026-07-27.md](docs/Token_Optimierungs_Plan_2026-07-27.md) — Optimierungsstrategie
