# Code-Archiv — Adaptive Planner Integration
**Datum:** 2026-07-25  
**Meilenstein:** adaptive_planner_2026-07-25

---

## 📁 Struktur

```
code/
├── run_adaptive.py                      ← Neuer Entrypoint (ohne Snake/Counter-Altlasten)
├── engine/
│   ├── services/
│   │   ├── guardian.py                  ← Task-Limit auf 10 erhoeht
│   │   └── scope_policy.py              ← Delta-Erkennung & Scope-Policy
│   └── transport/
│       └── pi_mesh_transport.py          ← Adaptive Prompts (RESEARCHER + PLANNER)
└── tests/
    └── test_guardian_plan_validation.py ← Tests fuer Task-Limit
```

---

## 🔑 Wichtige Aenderungen

### 1. `run_adaptive.py`
**Was:** Neuer Entrypoint fuer adaptive Planung  
**Warum:** `run_pi_mesh.py` war fuer Snake/Counter, brauchten sauberen neuen Startpunkt  
**Aenderungen:**
- Docstring mit vollstaendiger Dokumentation
- `_snake_config()` → `_adaptive_config()`
- Log-Messages: "Starting Adaptive Run..." / "Adaptive Run finished"
- DB-Name: `snake_pimesh.db` → `adaptive.db`

### 2. `engine/services/guardian.py`
**Was:** Task-Limit von 5 auf 10 erhoeht  
**Warum:** Planner soll bis zu 10 Tasks erstellen koennen  
**Aenderungen:**
- `MAX_TASKS = 5` → `MAX_TASKS = 10`
- Fehlermeldung: "max 5 tasks" → "max 10 tasks"
- Tests aktualisiert

### 3. `engine/transport/pi_mesh_transport.py`
**Was:** Adaptive Prompts fuer RESEARCHER und PLANNER  
**Warum:** Planner soll Delta vs. Neubau erkennen und entsprechend planen  
**Aenderungen:**
- **RESEARCHER Prompt:**
  - Delta-Erkennung: "Wenn Projekt bereits Dateien enthaelt → nur Aenderung planen"
  - Beispiel: "Contact-Sektion hinzufuegen" statt "Erstelle eine Website"
- **PLANNER Prompt:**
  - Delta-Erkennung: "Wenn Research Brief von Aenderung spricht → plane nur Aenderung (1-3 Tasks)"
  - "Wenn Research Brief von Neubau spricht → plane vollstaendig (3-10 Tasks)"

### 4. `engine/services/scope_policy.py`
**Was:** Scope/Protected-Files-Logik fuer Delta-Modus  
**Warum:** Bei bestehenden Projekten sollen nur geaenderte Dateien bearbeitet werden  
**Aenderungen:**
- `compute_protected_files()`: Berechnet protected_files aus allen Projektdateien minus scope_files
- `apply_ingest_scope()`: Wendet Ingest-Scope auf Task-Definition an

### 5. `tests/test_guardian_plan_validation.py`
**Was:** Tests fuer erhoehtes Task-Limit  
**Warum:** Sicherstellen, dass 11 Tasks abgelehnt, 10 Tasks akzeptiert werden  
**Aenderungen:**
- Test von 6 Tasks auf 11 Tasks aktualisiert
- Assertions fuer "max 10" angepasst

---

## 🧪 Test-Coverage

### Guardian-Validation
```python
# Test 1: 11 Tasks werden abgelehnt
assert validate_plan_draft(plan_11) == (False, ["max 10 tasks"])

# Test 2: 10 Tasks werden akzeptiert
assert validate_plan_draft(plan_10) == (True, [])

# Test 3: 1 Task wird akzeptiert (adaptiv)
assert validate_plan_draft(plan_1) == (True, [])
```

### Integrationstest (Run dd05bfd8)
- **Researcher:** Erkannte Delta (bestehendes Projekt)
- **Planner:** Erstellte 2 Tasks (statt 3)
- **Coder:** Implementierte SEO + Kontakt-Sektion
- **Scope-Policy:** app.js protected, nicht veraendert
- **Status:** COMPLETED in ~5 Minuten

---

## 🔄 Rollback

Falls Probleme auftreten:
```bash
# Alten Entrypoint verwenden
export FIRMA_TRANSPORT=in-process
python run_snake.py
```

---

## 📝 Changelog

| Datum | Datei | Aenderung | Grund |
|-------|-------|-----------|-------|
| 2026-07-25 | `run_adaptive.py` | Neu erstellt | Sauberer Entrypoint ohne Snake/Counter-Altlasten |
| 2026-07-25 | `guardian.py` | MAX_TASKS: 5 → 10 | Planner soll bis zu 10 Tasks erstellen koennen |
| 2026-07-25 | `pi_mesh_transport.py` | RESEARCHER + PLANNER Prompts | Delta-Erkennung und adaptive Planung |
| 2026-07-25 | `scope_policy.py` | `apply_ingest_scope()` | Protected-Files fuer Delta-Modus |
| 2026-07-25 | `test_guardian_plan_validation.py` | Tests aktualisiert | MAX_TASKS = 10 |
