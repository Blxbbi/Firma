# 🎯 Zielarchitektur

Du baust:

> Eine deterministische AI‑Execution‑Engine  
> mit pi‑messenger als Kommunikations‑Backbone.

Die Kontrolle liegt **nicht** bei Agenten.  
Nicht bei Crew.  
Nicht bei Swarm.  

Sondern bei **deiner Engine**.

---

# 🧱 High-Level Architektur

```
                ┌────────────────────┐
User Input ───▶ │ Planning Worker    │ (LLM)
                └─────────┬──────────┘
                          │
                          ▼
                ┌────────────────────┐
                │ PLAN REGISTRY      │  ← Single Source of Truth
                └─────────┬──────────┘
                          │
                          ▼
                ┌────────────────────┐
                │ EXECUTION ENGINE   │  ← State Machine
                └─────────┬──────────┘
                          │
        ┌─────────────────┴─────────────────┐
        ▼                                   ▼
┌──────────────┐                     ┌──────────────┐
│ Coder Worker │  <──pi-messenger──▶  │ Verifier     │
└──────────────┘                     └──────────────┘
                          │
                          ▼
                ┌────────────────────┐
                │ ARTIFACT STORE     │
                └────────────────────┘
```

---

# 🔹 Rolle von pi‑messenger

Du nutzt pi‑messenger nur für:

### ✅ 1. Strukturierte Task-Zuweisung
Engine sendet:

```json
{
  "type": "task_assignment",
  "task_id": "T1",
  "payload": {...}
}
```

an Worker-Agent.

---

### ✅ 2. File Reservation
Bevor Coder arbeitet:

```bash
reserve src/auth/
```

Engine prüft Lock-Status.

---

### ✅ 3. Ergebnis-Rückmeldung

Worker sendet:

```json
{
  "type": "task_result",
  "task_id": "T1",
  "artifacts": {...}
}
```

zurück an Engine.

---

Wichtig:
Messenger ist nur Transport.
Nicht Logik.

---

# 🧠 Deine Kernkomponenten (selbst gebaut)

---

## 1️⃣ Plan Registry

Speichert:

```json
{
  "plan_id": "P1",
  "tasks": [...],
  "status": "PLANNED"
}
```

Eigenschaften:

- Immutable Versionierung
- Jede Task hat:
  - id
  - description
  - expected_artifacts
  - acceptance_criteria
  - dependencies

Das ist deine Wahrheit.

---

## 2️⃣ Execution Engine (State Machine)

Das Herzstück.

Beispiel-States pro Task:

```
PLANNED
READY
CLAIMED
IN_PROGRESS
SUBMITTED
FAILED
VERIFIED
```

Transitions sind **hart kodiert**.

Beispiel:

```
SUBMITTED → VERIFIED
nur wenn:
- alle expected_artifacts existieren
- keine extra Artefakte
- Tests bestehen
```

Nicht der Agent entscheidet.
Nicht Messenger.
Nur deine Engine.

---

## 3️⃣ Artifact Store

Speichert:

```
/artifacts/{plan_id}/{task_id}/
```

Mit:

- Versionierung
- Hashes
- Diff-Möglichkeiten

Engine prüft:

- Fehlt Datei?
- Falscher Name?
- Unerwartete Datei?

Das ist deterministisch prüfbar.

---

## 4️⃣ Validation Layer

Mehrstufig:

### Level 1 – Struktur
- Dateien vorhanden?
- Namen korrekt?
- JSON-Schema korrekt?

### Level 2 – Static Analysis
- Funktion existiert?
- Signatur korrekt?
- Imports korrekt?

### Level 3 – Sandbox Execution
- Tests laufen?
- Exit-Code?
- Exceptions?

Alles infra-gesteuert.

---

# 🔄 Beispiel-Ablauf

User:

> Baue OAuth Login

---

## Schritt 1 – Planning Worker

LLM erzeugt strukturierten Plan.

Engine speichert.

---

## Schritt 2 – Engine aktiviert Task T1

Sendet via pi-messenger:

```json
assign_task(T1)
```

---

## Schritt 3 – Coder

- reserviert src/auth/
- implementiert
- sendet Result zurück

---

## Schritt 4 – Engine validiert

Checkliste:

- Datei auth.py existiert? ✅
- Funktion login() existiert? ✅
- Test vorhanden? ❌

→ Status = FAILED  
→ Task zurück in READY

---

Kein Agent „merkt“ das.  
Die Engine erzwingt es.

---

# 🚫 Was du bewusst NICHT nutzt

### ❌ Crew Task Graph
Weil:
Du deine eigene Plan Registry hast.

### ❌ Swarm Spawn
Weil:
Du keine emergenten Rollen willst.

### ❌ Channel-basierte Entscheidungsfindung
Weil:
Du keine Diskussion als Wahrheitsquelle willst.

---

# ✅ Optional sinnvoll aus Swarm

Wenn du willst:

Du könntest Channels rein als:

```
#architecture-log
#decision-log
#memory
```

verwenden.

Aber:
Nur als Protokoll.
Nicht als Kontrollinstanz.

---

# 🏗 Tech-Stack-Vorschlag (minimal MVP)

- Python Backend
- FastAPI oder reines Service-Modul
- SQLite/Postgres für Plan Registry
- File-based Artifact Store
- Docker Sandbox für Execution
- pi-messenger nur als Agent-Bridge

---

# 🔥 Ergebnis

Du erhältst:

- Voll kontrollierte AI-Pipeline
- Austauschbare Worker (LLM-Modell egal)
- Deterministische Prozesskontrolle
- Reproduzierbarkeit
- Kein emergentes Chaos

---

# 🧭 Architekturelle Essenz

pi-messenger = Nervenbahnen  
LLMs = Muskeln  
Deine Engine = Gehirn  
State Machine = Gesetz  
Plan Registry = Verfassung  

---

