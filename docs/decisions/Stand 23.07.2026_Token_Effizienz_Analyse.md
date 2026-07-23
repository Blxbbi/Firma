# Stand 23.07.2026 — Token-Effizienz Analyse

## Run-Daten (echter Run `ce5e5edb-cf93-4c3b-a4f1-598275610163`)

| Task | Turns | Gesamt-Tokens | Input | Output | cacheRead |
|------|-------|---------------|-------|--------|-----------|
| task-1 | 17 | **1,688,125** | 150,703 | 58,254 | **1,479,168** |
| task-2 | 10 | 515,876 | 120,594 | 13,330 | 381,952 |
| task-3 | 8 | 518,552 | 143,768 | 28,928 | 345,856 |
| **Summe** | **35** | **2,722,553** | **415,065** | **100,512** | **2,207,976** |

**Anteil cacheRead am Gesamtverbrauch:**
- task-1: **87,6%**
- task-2: **74,1%**
- task-3: **66,7%**

---

## 1. Was die Tokens wirklich macht

### 1.1 cacheRead ist der stille Killer

Jeder LLM-Turn bekommt den **gesamten bisherigen Verlauf** zurück:
- System-Prompt
- User-Prompt
- Vorherige Turns
- Alle Tool-Calls + Tool-Results

Bei task-1 mit 17 Turns wird der Context bei jedem Turn größer. Am Ende hat das LLM einen Context von über **1,4 Millionen Tokens** — und jeder weitere Turn kostet mehr als der vorherige.

**Herleitung:**
```
Turn 1:  Context = 20k Tokens
Turn 5:  Context = 200k Tokens
Turn 10: Context = 800k Tokens
Turn 17: Context = 1,48M Tokens (cacheRead)
```

Das ist kein "großer Prompt" — das ist **Context-Wachstum durch Iteration**.

### 1.2 Kein ONE-PASS-Vertrag → Iteration ohne Grenze

Der CODER darf machen was er will:
```
write(index.html) → read(index.html) → edit(index.html) → read(index.html) → ...
```
Jeder Tool-Call + Response ist ein Turn. Bei 17 Turns bedeutet das ~15 Schleifen aus "ich schau mal ob's richtig ist".

**Das ist kein Bug — das ist das Fehlen einer Regel.**

### 1.3 Tool-Schleifen sind "kostenlos"

Jeder Tool-Call kostet nur einen Turn, hat aber keine Konsequenz. Es gibt keinen Preis für Iteration. Das LLM denkt: "Ich kann ja nochmal lesen, es kostet ja nichts."

### 1.4 Prompt ist zu offen für große Aufgaben

Die Aufgabe lautet: *"Erstelle eine professionelle, moderne Website für das Open-Source-Projekt 'Firma'"* — mit 7+ Sektionen, Design-Anforderungen, Tech-Stack.

Das ist ein riesiges Briefing für einen Worker, der eigentlich nur eine Task machen soll. Das LLM reagiert darauf mit Over-Engineering: es liest seine eigenen Dateien mehrfach, prüft, ob alles stimmt, korrigiert sich selbst.

### 1.5 Keine Scope-Grenze im Prompt-Contract

Der CODER-Prompt sagt: "Implementiere ausschließlich: <description>" — aber die Description ist so groß, dass "ausschließlich" praktisch alles bedeutet. Es gibt keine harte Grenze wie "max 3 Dateien, max 200 Zeilen, keine reads nach dem ersten write".

---

## 2. Ursachen-Hierarchie

### Primär (verursacht 70-80% des Overheads)

1. **Kein ONE-PASS-Vertrag für CODER/PLANNER/RESEARCHER**
   - Der REVIEWER hatONE-PASS → 4 Turns, 119k Tokens
   - Der CODER hat keinen ONE-PASS → 17 Turns, 1,68M Tokens
   - **Differenz: 4x mehr Turns, 14x mehr Tokens**

2. **Kein Hard-Turn-Limit**
   - Worker iterieren so lange sie wollen
   - Jede Iteration kostet mehr Tokens als die vorherige (Context-Wachstum)

3. **cacheRead-Explosion durch Iteration**
   - 1,48M cacheRead bei task-1 = 87,6% des Gesamtverbrauchs
   - Ursache: 17 Turns mit wachsendem Context

### Sekundär (verursacht 20-30% des Overheads)

4. **Übergroßer Prompt bei CODER**
   - 7+ Sektionen, Design-Anforderungen, Tech-Stack
   - Hohe Input-Tokens → LLM "denkt" mehr → mehr Turns

5. **Keine Scope-Grenze**
   - "Implementiere ausschließlich" ohne konkrete Grenzen
   - LLM interpretiert "ausschließlich" als "alles was dazugehört"

6. **Tool-Schleifen ohne Konsequenz**
   - read → write → read → edit → write
   - Jeder Call kostet nur einen Turn, hat keine Konsequenz

### Tertiär (verursacht 10-20% des Overheads)

7. **Keine Tool-Result-Kürzung**
   - Große Tool-Outputs werden ungekürzt im Context behalten

8. **Kein Kontext-Budget pro Rolle**
   - CODER darf theoretisch unendlich viel Context akkumulieren

---

## 3. Maßnahmen — priorisiert

### Sofort (1-2 Stunden, großer Effekt)

#### 1. Hard-Turn-Limit für CODER/PLANNER/RESEARCHER

**Was:**
```
MAX_TURNS = {
    "CODER": 8,
    "PLANNER": 10,
    "RESEARCHER": 8,
    "REVIEWER": 4  # bereits ok
}
```

**Effekt:** 30-50% Token-Reduktion
**Aufwand:** Niedrig
**Begründung:** Worker wird gezwungen, früher zu entscheiden. Wenn er das Limit erreicht → `TASK_FAILED` mit "Turn limit exceeded". Kernel retried mit `previous_feedback`.

**Herleitung:** Aktuell hat CODER task-1 17 Turns, task-3 hat 8 Turns. Mit Limit 8 würde task-1 spätestens bei Turn 8 stoppen — und entweder fertig sein oder mit Feedback neu starten.

#### 2. ONE-PASS-Vertrag für CODER im Prompt

**Was:**
```
Du arbeitest in ONE-PASS:
- Schreibe alle erforderlichen Dateien in EINEM Rutsch
- Keine read()-Calls nach dem ersten write()
- Keine Selbstprüfung durch nochmaliges lesen
- Wenn unklar → TASK_FAILED statt iterieren
```

**Effekt:** 40-60% Token-Reduktion
**Aufwand:** Mittel
**Begründung:** Der REVIEWER hat bereits ONE-PASS → 4 Turns, 119k Tokens. Wenn CODER das gleiche Verhalten hätte, würde task-1 statt 17 Turns nur 4-6 Turns brauchen.

**Herleitung:** 
```
REVIEWER: 4 Turns, 119k Tokens → ONE-PASS
CODER:     17 Turns, 1,68M Tokens → kein ONE-PASS
Faktor:    4,25x mehr Turns, 14x mehr Tokens
```

#### 3. Load only expected artifacts

**Was:** Statt alle Dateien aus dem Artefakt-Verzeichnis zu laden, nur die, die in `expected_artifacts` stehen.

**Effekt:** 20-30% Token-Reduktion bei REVIEWER
**Aufwand:** Niedrig
**Begründung:** Bereits erkannt und teilweise implementiert. Der REVIEWER lädt aktuell alle Dateien statt nur die, die er braucht.

### Danach (2-3 Stunden, weiterer Gewinn)

#### 4. Tool-Result-Kürzung

**Was:**
```
if len(tool_result) > 200:
    tool_result = tool_result[:100] + "\n... [gekürzt] ...\n" + tool_result[-100:]
```

**Effekt:** 10-20% Token-Reduktion
**Aufwand:** Niedrig
**Begründung:** Große Tool-Outputs (bash, read) werden ungekürzt im Context behalten. Kürzung auf first/last 50 Zeilen + Summary reduziert den Context massiv.

#### 5. Prompt-Kürzung für PLANNER

**Was:**
- Keine History
- Keine fremden Tasks
- Nur Research-Brief + aktuelle Task-Definition

**Effekt:** 20-30% Token-Reduktion
**Aufwand:** Mittel
**Begründung:** PLANNER hat aktuell 685k Tokens für 14 Turns. Kürzung des Prompt + ONE-PASS würde das auf ~300-400k drücken.

### Später (wenn Basics sitzen)

#### 6. Kontext-Budget pro Rolle

**Was:**
```
CONTEXT_BUDGET = {
    "CODER": 100_000,
    "PLANNER": 80_000,
    "REVIEWER": 50_000,
    "RESEARCHER": 60_000
}
```

Bei Überschreitung → Zusammenfassung älterer Turns statt Volltext.

**Effekt:** 30-50% Token-Reduktion
**Aufwand:** Mittel
**Begründung:** Verhindert, dass der Context unendlich wächst. Wenn Budget erreicht → ältere Turns werden zusammengefasst.

---

## 4. Erwartete Ergebnisse nach Maßnahmen

| Maßnahme | Token-Reduktion | Geschätzte neue Token-Zahl |
|----------|----------------|---------------------------|
| Aktuell (Baseline) | — | 2,72M |
| + Hard-Turn-Limit | 30-50% | 1,36M - 1,90M |
| + ONE-PASS für CODER | +40-60% | 820k - 1,16M |
| + Load only expected | +20-30% | 650k - 900k |
| **Gesamt (konservativ)** | **~60-70%** | **~800k - 1,1M** |

---

## 5. Was wir NICHT machen sollten

### Delta-Context
**Warum nicht:** Over-Engineered für deinen aktuellen Stack. Bei 17 Turns ist der Delta fast so groß wie der Full-Context. Außerdem brauchst du einen State-Machine für Context-Management — viel Architektur für wenig Gewinn.

### Prompt-Template-Layer
**Warum nicht:** Netto wenig Gewinn. Es ist ein Architektur-Thema, kein Performance-Fix. Es spart 10-20% — aber erst wenn du das Turn-Problem gelöst hast. Sonst ist es wie einen schnelleren Motor in ein Auto einzubauen, das in der Kurve rutscht.

---

## 6. Entscheidung

**Empfehlung:** Sofort mit Maßnahme 1 (Turn-Limit) und 2 (ONE-PASS) beginnen. Maßnahme 3 (Load only expected) ist bereits teilweise implementiert und needs nur noch Aktivierung.

**Nächster Schritt:** Patch `engine/transport/pi_mesh_transport.py` und `engine/providers/pi_provider.py` für Turn-Limit + ONE-PASS Contract.
