# Firma — Multi-Agent Runtime Engine

`engine/` ist der Kern: eine asynchrone Orchestrator-Runtime, die Spezifikationen
in Tasks zerlegt, Worker (Planner/Executor) dispatcht, deren Output durch eine
Guardian-Pipeline validiert und Ergebnisse in SQLite persistiert.

## Struktur

| Pfad | Rolle |
|------|-------|
| `engine/` | Runtime-Logik: Orchestrator, Scheduler, Services, Provider, Transport |
| `workers/` | Worker-Rollen (Planner, Executor) |
| `platform/` | Entrypoints / Lifecycle (main.py, run_snake.py, run_pi_mesh.py) |
| `docs/` | Strategie, Architektur, Tagesberichte |
| `tests/` | Test-Suites (inkl. adversarial / chaos / evil-worker) |
| `benchmarks/` | Telemetrie & Benchmarking |
| `data/` | Laufzeit-Zustand (DB + Artefakte, via .gitignore ignoriert) |
| `archive/` | Read-only Historie & Legacy-Skripte |

Siehe `docs/PROJECT_LAYOUT.md` für die vollständigen Zustands- und
Aufräum-Regeln (Root-Sauberkeit, Run-Scoped-Artefakte, Retention).

## Quickstart

```bash
# Abhängigkeiten
pip install -r requirements.txt

# Engine starten
python platform/main.py
# oder Snake-Szenario
python platform/run_snake.py
```

## Provider

LLM-Anbieter sind in `engine/providers/` als Strategy gekapselt
(mock, openai, openrouter, nvidia, manual, pi, stochastic).
Transport (in-process vs. PiMesh) über `FIRMA_TRANSPORT` wählbar.

## Status

Aktiver Branch: `chore/clean-architecture`. Repository-Historie von Logs/DBs/.pyc
bereinigt (`backup-before-clean-20260714` hält die alte Historie).
Offene Punkte: `requirements.txt`/`pyproject.toml` fehlt, CI fehlt.
