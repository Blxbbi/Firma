# Meilenstein: Adaptive Planner Integration
**Datum:** 2026-07-25  
**Status:** ✅ Erfolgreich abgeschlossen  
**Run-ID:** dd05bfd8-8572-4def-bf19-efea8d679384

---

## 🎯 Ziel

Firma von einem starren 3-Task-System zu einem **intelligenten, adaptiven Workflow** weiterentwickeln, bei dem der Planner basierend auf der Projektkomplexität selbst entscheidet, wie viele Tasks erstellt werden.

---

## ✅ Was erreicht wurde

### 1. **Adaptive Planung (Bewiesen)**
- **Vorher:** Planner erstellte **immer 3 Tasks** (index.html, style.css, app.js) — unabhängig von der Aufgabenstellung
- **Jetzt:** Planner entscheidet selbst:
  - Einfache Aufgabe → 1-2 Tasks
  - Mittlere Komplexität → 3-5 Tasks
  - Komplexe Projekte → 6-10 Tasks
- **Beweis:** Run dd05bfd8 erstellte nur **2 Tasks** für eine Delta-Erweiterung

### 2. **Task-Limit erhöht**
- **Vorher:** Max 5 Tasks (Kernel-Guard)
- **Jetzt:** Max 10 Tasks (Kernel-Guard)
- **Datei:** `engine/services/guardian.py`
- **Test:** `tests/test_guardian_plan_validation.py` aktualisiert

### 3. **Delta-Erkennung implementiert**
- **Researcher** erkennt automatisch:
  - **Delta-Modus:** Projekt hat bereits Dateien → nur Änderungen planen
  - **Greenfield-Modus:** Projekt ist leer → vollständige Implementierung planen
- **Datei:** `engine/transport/pi_mesh_transport.py` (RESEARCHER + PLANNER Prompts)

### 4. **Config befreit**
- `expected_artifacts: []` (Planner entscheidet)
- `acceptance_criteria: []` (Planner definiert)
- **Datei:** `run_adaptive.py` → `_adaptive_config()`

### 5. **Neuer Entrypoint**
- **Datei:** `run_adaptive.py`
- **Status:** Alle Snake/Counter-Referenzen ersetzt durch "Adaptive"
- **Zweck:** Sauberer Einstiegspunkt für zukünftige Tests

---

## 🧪 Test-Ergebnis (Run dd05bfd8)

### Ausgangssituation
- **Projekt:** `test-project/` (bestehende Website mit index.html, style.css, app.js)
- **Aufgabe:** "Füge eine Contact-Sektion hinzu"
- **Modus:** Delta (Ingest mit bestehendem Projekt)

### Was der Planner gemacht hat

#### task-1: SEO-Meta-Tags (nicht gewünscht!)
- `<meta name="description">`
- Favicon (SVG)
- Open-Graph-Tags
- Twitter-Card-Tags

#### task-2: Kontakt-Sektion (gewünscht!)
- Neuer Nav-Link: `#contact`
- Section mit GitHub-Link und E-Mail-Link
- Grid-Layout für Kontakt-Karten
- Hover-Effekte und Icons

### Scope/Protected-Files (Funktioniert!)
- **task-1:** `scope=['index.html']`, `protected=['app.js', 'style.css']`
- **task-2:** `scope=['index.html', 'style.css']`, `protected=['app.js']`
- **Ergebnis:** `app.js` wurde **nicht verändert** ✅

### Endprodukt
```
data/artifacts/dd05bfd8-8572-4def-bf19-efea8d679384/task-2/
├── index.html (18 KB)  ← +SEO-Meta-Tags +Kontakt-Sektion
├── style.css (10 KB)   ← +Contact-Styles
└── app.js              ← NICHT VERÄNDERT (protected)
```

---

## 📊 Vergleich: Vorher vs. Nachher

| Aspekt | Vorher | Nachher |
|--------|--------|---------|
| **Task-Anzahl** | Immer 3 | Adaptiv (1-10) |
| **Delta-Erkennung** | ❌ Nein | ✅ Ja |
| **Scope-Policy** | ✅ Ja | ✅ Ja |
| **Researcher Brief** | Immer "Neubau" | Delta vs. Neubau |
| **Planner Freiheit** | ❌ Nein | ✅ Ja |
| **Kernel-Guards** | ✅ Max 5 Tasks | ✅ Max 10 Tasks |

---

## 🚀 Nächste Schritte

### Kurzfristig
- [ ] Weitere Delta-Tests mit verschiedenen Projekt-Arten
- [ ] Planners "Scope Creep" beobachten (welche Extras fügt er hinzu?)
- [ ] Priority-Feld evaluieren (optional)

### Mittelfristig (Phase B)
- [ ] **Delta-Planung verfeinern:**
  - `edit_mode` Flag für bestehende Projekte
  - Nur geänderte Dateien werden committed
  - Protected-Files-Logik erweitern
- [ ] **Agent Modularity:**
  - `agents.yaml` für toggling (Researcher/Planner/Coder/Reviewer on/off)

### Langfristig (Phase C)
- [ ] Iterative Delta-Planung (Run 2 baut auf Run 1 auf)
- [ ] Multi-Projekt-Support
- [ ] Concurrent Task-Ausführung (wenn Dateien nicht kollidieren)

---

## 📁 Relevante Dateien

### Geändert
- `run_adaptive.py` — Neuer Entrypoint (ohne Snake/Counter-Altlasten)
- `engine/services/guardian.py` — Max 10 Tasks
- `engine/transport/pi_mesh_transport.py` — Adaptive Prompts für Researcher + Planner
- `tests/test_guardian_plan_validation.py` — Tests aktualisiert

### Architektur
```
run_adaptive.py
  └─ _adaptive_config()
      └─ expected_artifacts: []
      └─ acceptance_criteria: []
      └─ PLANNER-HINWEIS (Budget-Info)

engine/transport/pi_mesh_transport.py
  ├─ RESEARCHER Prompt
  │   └─ Delta-Erkennung (bestehend vs. neu)
  └─ PLANNER Prompt
      └─ Delta-Erkennung (1-3 Tasks für Änderung, 3-10 für Neubau)

engine/services/guardian.py
  └─ validate_plan_draft()
      └─ Max 10 Tasks
      └─ Max 3 expected_artifacts pro Task
```

---

## 🎓 Learnings

1. **Adaptive Planung funktioniert** — Der Planner kann selbst entscheiden, wie viele Tasks erstellt werden
2. **Delta-Erkennung ist entscheidend** — Ohne sie würde der Planner immer "Neubau" planen
3. **Kernel-Guards bleiben stabil** — Auch mit adaptivem Planner bleiben die deterministischen Limits erhalten
4. **Scope Creep ist real** — Der Planner neigt dazu, "sinnvolle" Dinge hinzuzufügen (SEO-Tags), die nicht verlangt wurden
5. **Tests sind essenziell** — Ohne sauberes Cleanup vor dem Test wurden alte DB-Daten verwendet, die zu 5 Tasks führten

---

## 🔗 Verwandte Dokumente

- `docs/Statusbericht_Planner_Erweiterung_2026-07-25.md` — Ausführlicher Statusbericht für Advisor
- `milestones/happy_path_13_07_2026/` — Vorheriger Meilenstein
- `milestones/reviewer_optimization_and_backup_2026-07-23/` — Vorheriger Meilenstein

---

## 🏆 Fazit

**Die adaptive Planner-Integration ist erfolgreich!** 

Der Planner ist jetzt **adaptiv** und entscheidet selbst, wie viele Tasks erstellt werden. Die Delta-Erkennung funktioniert, die Kernel-Guards bleiben intakt, und das System ist bereit für Phase B (Delta-Planung verfeinern).

**Nächster Meilenstein:** Phase B — Delta-Planung als First-Class-Feature
