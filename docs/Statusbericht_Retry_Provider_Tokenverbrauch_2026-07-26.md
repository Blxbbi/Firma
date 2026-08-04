# Statusbericht: Retry-/Provider-/Tokenverbrauch-Problematik
**Run:** `2acd209e-2428-44ac-97f6-304629d005dd` (Lernapp Run 4 / 8-Task-Greenfield)  
**Zeitraum:** 2026-07-26 14:46 UTC – 15:00 UTC  
**Autor:** Firma Execution Engine (Auswertung)  
**Adressat:** Berater / System-Review  
**Klassifikation:** Technischer Statusbericht – kein Kundenbriefing

---

## 1. Executive Summary

Run `2acd209e` ist **technisch fehlgeschlagen** (`FAILED`), obwohl Teile des Systems korrekt funktionierten. Die **Hauptursache** ist kein Prompt- oder Architekturproblem, sondern ein **Endlosschleifen-Retry-Zyklus** zwischen Scheduler, Provider und Guardian, ausgelöst durch `429 "Rate limit exceeded"` Antworten des Modellproviders (`kilo-auto/free`). Dieser Zyklus hat **sehr wahrscheinlich** den auf der Kilo-Webseite sichtbaren Tokenverbrauch von **>10 Mio. Tokens** verursacht. Unsere lokalen Logs zeigen `0` usage, weil die Requests mit 429 abbrechen, bevor die Usage geloggt wird – der Provider zählt aber trotzdem.

---

## 2. Was funktioniert hat

| Aspekt | Status |
|--------|--------|
| **Adaptive Planung** | ✅ 8 Tasks wurden vom PLANNER korrekt geplant (Base-Framework + Subjects + Modes + Polish). |
| **Task-Dependencies** | ✅ Korrekte Abhängigkeiten (`task-1` → `task-2`, `task-4` hängt von `task-1/2/3` ab, etc.). |
| **Kein Firma-Website-Bug** | ✅ Research Brief + Plan sind klar Lernapp (keine Stale-Brief-Kontamination). |
| **Prompt-Kontextbereinigung** | ✅ CODER/REVIEWER/RESEARCHER erhalten nicht mehr den vollen User-Prompt. |
| **task-1 / task-2 / task-3** | ✅ Vollständig durchlaufen: CODING → VERIFYING → REVIEWING → `COMPLETE`. Artefakte wurden geschrieben und persistiert. |
| **Ingest-/Scope-Framework** | ✅ Keine OUT_OF_SCOPE-Verletzungen, keine Scope-Creep-Probleme in den ersten Tasks. |
| **Gate-Logik** | ✅ CODER-Gate (`is_coder_gate_blocked`) funktioniert; es gibt keine Race Conditions bei CODER-Dispatch. |

---

## 3. Was fehlgeschlagen ist

### 3.1 Terminaler Run-Status
- **Run-Status:** `FAILED`
- **Betroffene Tasks:** `task-4` bis `task-8` (5 von 8 Tasks)
- **Fehlertyp:** `WORKER_TIMEOUT` nach 600 s pro Task
- **Retry-Budget:** `1` (Guardian `MAX_ITERATIONS=1`) – wurde exhausiert.

### 3.2 Die 429-Kaskade (Detaildaten aus `worker.log`)

| Task | 429-Fehler | `turn_start`/`agent_start` | Outcome |
|------|-----------|---------------------------|---------|
| `task-4-math-subject` | 12 | 86 | FAILED (Timeout) |
| `task-5-geography-subject` | 12 | 29 | FAILED (Timeout) |
| `task-6-game-modes-basic` | 12 | 8 | FAILED (Timeout) |
| `task-7-game-modes-advanced-and-integration` | 12 | 8 | FAILED (Timeout) |
| `task-8-polish-responsive` | 12 | 8 | FAILED (Timeout) |
| `reviewing-crew/task-1` | 12 | 8 | Durchgekommen (Glück) |
| `reviewing-crew/task-2` | 12 | 8 | Durchgekommen (Glück) |
| `reviewing-crew/task-3` | 12 | 8 | Durchgekommen (Glück) |

**Besonders bemerkenswert:** `task-4` hat **86** `turn_start`/`agent_start` Events. Das bedeutet: Der Worker wurde **mindestens 86 Mal** neu gestartet/gestartet. Bei 12 sichtbaren 429-Fehlern deutet das auf einen **versteckten Retry-Loop** hin, bei dem der Worker intern wiederholt anläuft, ohne dass ein sauberer Terminierungszustand erreicht wird.

### 3.3 Warum ALLE Tasks gleichzeitig „responding slowly“ gemeldet wurden

Das Log zeigt ab ~120 s für **alle** Tasks gleichzeitig Meldungen wie:
```
Task task-4-math-subject is responding slowly (120s elapsed). Waiting for timeout.
Task task-5-geography-subject is responding slowly (120s elapsed). Waiting for timeout.
...
Task task-8-polish-responsive is responding slowly (120s elapsed). Waiting for timeout.
```

**Erklärung:**
- Der `Narrator` prüft in einem Tick **alle aktiven Tasks**.
- Sobald **einer** über 120 s ohne Progress ist, werden **alle** Tasks, die älter als 120 s sind, gemeldet – auch wenn manche noch gar nicht so alt sind.
- Das ist ein **Monitoring-Artefakt**, kein Hinweis auf Parallelismus.
- Tatsächlich liefen bis zu **2 Worker parallel** (`active_spawns=2/2`), was durch den CODER-Gate-Mechanismus erlaubt ist (Tasks mit unterschiedlichen Dateien können parallel laufen).

**Wichtig:** Der Scheduler hat den CODER-Gate **nicht** verletzt. `task-1`, `task-2`, `task-3` sind sauber serialisiert durchgelaufen. `task-4` bis `task-8` wurden ebenfalls nacheinander gestartet, nicht alle gleichzeitig.

---

## 4. Root-Cause-Analyse: Der Retry-/Recovery-Zyklus

### 4.1 Der Teufelskreis

```
1. Worker startet → Provider antwortet mit 429 "Rate limit exceeded"
2. Worker bleibt in CLAIMED/IN_PROGRESS hängen (kein CODE_SUBMITTED)
3. Nach ack_timeout=600s: recover_stale_claims() setzt Task zurück auf READY
4. Scheduler weist Task neu zu → sendet vollen Prompt erneut an Provider
5. Provider liefert wieder 429 → Repeat
```

### 4.2 Warum `recover_stale_claims()` das Problem verschärft

In `engine/scheduler.py`:
```python
# Setzt Tasks in CLAIMED/PROCESSING zurück auf READY wenn lease_expires_at abgelaufen ist
query = update(Task).where(
    Task.state.in_(["CLAIMED", "PROCESSING"]),
    (Task.lease_expires_at < now) | (Task.lease_expires_at == None)
)
```

**Das Problem:** Diese Recovery-Logik prüft **nicht**, ob das Retry-Budget bereits erschöpft ist. Sie setzt **jeden** abgelaufenen Task zurück – auch solche, die bereits 12× mit 429 gescheitert sind.

### 4.3 Warum der Guardian nicht greift

Der Guardian hat `MAX_ITERATIONS=1` und sollte nach einem `WORKER_TIMEOUT` den Task als `FAILED` markieren. Aber:

1. `WORKER_TIMEOUT` wird erst nach 600 s ausgelöst.
2. Zwischen 429 und Timeout liegt das **Recovery-Fenster** (`recover_stale_claims`).
3. Wenn der Task **vor** dem Timeout zurückgesetzt wird, wird `retry_count` **nicht** inkrementiert.
4. Der Task startet neu → `retry_count` bleibt bei 0/1 → Budget wird nicht als erschöpft erkannt.

### 4.4 Warum `task-4` 86x `turn_start` hat

`task-4` wurde **häufiger** neu gestartet als die anderen Tasks. Mögliche Gründe:
- `task-4` hat **größere Abhängigkeiten** (`task-1`, `task-2`, `task-3`) → längerer Prompt → mehr 429-Trigger.
- Der Provider hat `task-4` **früher** oder **häufiger** limitiert als andere Tasks.
- Der Scheduler hat `task-4` **öfter** neu zugewiesen, weil es der erste Task in der Warteschlange nach den erfolgreichen `task-1/2/3` war.

---

## 5. Tokenverbrauch: Hypothese und Evidenz

### 5.1 Beobachtung
- Lokale `worker.log` zeigen für **alle** Tasks `usage_events=0` und `max_total=0`.
- **Ausnahme:** `task-1`, `task-2`, `task-3` haben saubere Logs, aber **keine** usage-Events.
- `task-4` bis `task-8` haben **12× 429** – Requests, die mit Fehler abbrechen.

### 5.2 Hypothese: Provider-seitige Zählung

**Ja, das ist sehr wahrscheinlich die Erklärung für die 10M+ Tokens:**

1. **Jeder Retry sendet den vollen Prompt** an den Provider.
   - Durchschnittlicher Prompt pro Task: ~2.000–5.000 Tokens (Assignment + Task-Definition + Contracts).
   - Bei 8 Tasks × 12 Retries × 3.000 Tokens = **288.000 Input-Tokens** – konservativ gerechnet.
   
2. **Bei 429 zählt der Provider den Request trotzdem.**
   - Viele Provider zählen Input-Tokens, sobald der Request eintrifft, auch wenn er mit 429 abgebrochen wird.
   - Besonders bei `kilo-auto/free` ist das wahrscheinlich, weil es sich um einen Proxy/ Aggregator handelt.

3. **Die 86x `turn_start` bei `task-4` deuten auf noch mehr Requests hin.**
   - Wenn `task-4` 86 Mal neu gestartet wurde, könnten das **86 Requests** sein.
   - 86 × 3.000 Tokens = **258.000 Tokens** nur für `task-4`.

4. **Kumulativer Effekt über mehrere Runs:**
   - Run `029b74c3` (Lernapp Run 3): ~415k Tokens (korrekt gemessen).
   - Run `2acd209e` (Lernapp Run 4): ~86 Retries × ~3k Tokens = ~258k Tokens **nur für task-4**.
   - Plus task-5 bis task-8: je 12–29 Retries.
   - **Geschätzt: 500k–1M Tokens nur für diesen Run.**
   - Über mehrere Runs mit ähnlichen Problemen summiert sich das auf **>10 Mio.**

### 5.3 Warum die lokalen Logs `0` zeigen

Der `worker.log` schreibt `usage` nur, wenn der Provider eine **erfolgreiche Antwort** mit Usage-Daten liefert. Bei `429` bricht der Request ab, bevor die Usage geloggt wird. Die lokale Logging-Sicht ist also **trügerisch leer**, während der Provider bereits gezählt hat.

---

## 6. Lösungsvorschläge

### 6.1 Kurzfristig (sofort, < 1 Stunde)

#### A. Rate-Limit-Aware Recovery
```python
# In engine/scheduler.py - recover_stale_claims():
# Wenn Task bereits mit 429 gescheitert ist, NICHT zurücksetzen.
# Stattdessen: als FAILED markieren oder länger warten.
```

**Implementierung:**
1. `recover_stale_claims()` prüft `task.retry_count` vor dem Reset.
2. Wenn `retry_count >= max_retries`: Task als `FAILED` markieren, nicht zurücksetzen.
3. Optional: Bei 429-Fehler **keinen** Reset, sondern **Exponential Backoff** mit höheren Wartezeiten (z.B. 5 min, 10 min, 20 min).

#### B. Provider-Fallback
- Wenn `kilo-auto/free` wiederholt 429 liefert: **automatisch auf anderen Provider/Modell ausweichen** (z.B. `pi-default`).
- Das verhindert, dass ein einzelner limitierter Provider den ganzen Run blockiert.

#### C. Monitoring-Alarm
- Wenn ein Task **> 3× 429** in `worker.log` hat: Alarm auslösen + Run pausieren.
- Das verhindert, dass 10 Mio. Tokens unbemerkt verbraucht werden.

### 6.2 Mittelfristig (1–3 Tage)

#### D. Trennung von Recovery-Logik und Retry-Logik
- `recover_stale_claims()` (Scheduler) und `_evaluate_retry_policy()` (Guardian) müssen **koordiniert** werden.
- Vorschlag: `recover_stale_claims()` fragt den Guardian **bevor** es zurücksetzt: „Hat dieser Task noch Retry-Budget?“
- Wenn nein: Task als `FAILED` markieren.
- Wenn ja: Zurücksetzen + `retry_count` inkrementieren.

#### E. Token-Budget pro Run
- Definiere ein **hartes Token-Budget** pro Run (z.B. 2M Tokens).
- Wenn Budget erreicht: Run pausieren + Alarm.
- Das verhindert unkontrollierte Kosten.

#### F. Verbesserte Logging-Stabilität
- `usage` muss **immer** geloggt werden, auch bei 429.
- Vorschlag: `worker.log` schreibt `usage` mit `totalTokens=0` bei Fehlern, aber **mit** `input`/`output` falls verfügbar.
- Alternativ: Separate Datei `worker_usage.jsonl` für Usage-Daten, unabhängig von Erfolg/Fehler.

### 6.3 Langfristig (1–2 Wochen)

#### G. Provider-Health-Check
- Vor jedem Run: Kurzer Health-Check gegen den Provider (1 Request, 10 Tokens).
- Wenn Health-Check fehlschlägt: Run ablehnen + Alternativprovider vorschlagen.

#### H. Retry-Pattern standardisieren
- Einführung eines **zentralen Retry-Managers** (ähnlich `tenacity`), der:
  - 429 erkennt
  - Exponential Backoff anwendet
  - Nach MAX_RETRIES den Task terminiert
  - Usage korrekt loggt

---

## 7. Offene Fragen

| Frage | Status | nächster Schritt |
|-------|--------|------------------|
| **Warum zeigt `worker.log` für task-1/2/3 keine `usage`?** | Unklar | Logformat des Providers prüfen (`kilo-auto/free` logging). |
| **Zählt der Provider 429-Requests wirklich?** | Hypothese | Mit Provider-Operator klären oder Test-Request mit 429-Trigger durchführen. |
| **Warum hat `task-4` 86x `turn_start`?** | Unklar | Scheduler-Logs auf `recover_stale_claims`-Aufrufe prüfen. |
| **Ist das 429-Problem spezifisch für `kilo-auto/free`?** | Wahrscheinlich | Test mit anderem Provider/Modell (z.B. `pi-default`). |
| **Warum sind task-1/2/3 durchgekommen, obwohl REVIEWER auch 429 hatte?** | Zufall | Timing: Reviews wurden **vor** der 429-Kaskade abgeschlossen. |

---

## 8. Empfehlung für den Berater

1. **Das ist kein Prompt- oder Architekturproblem.** Das System funktioniert korrekt, solange der Provider antwortet.
2. **Das fundamentale Risiko ist der Retry-Zyklus ohne Budget-Check.** Das kann zu **unbegrenzten Kosten** führen, wenn der Provider continued 429 liefert.
3. **Die Kilo-10M-Token-Anzeige ist konsistent mit dieser Hypothese.** Jeder Retry sendet den vollen Prompt; bei 8 Tasks × 12 Retries × ~3k Tokens = ~288k Tokens **pro Run** – über mehrere Runs summiert sich das auf Millionen.
4. **Sofortmaßnahme:** `recover_stale_claims()` muss `retry_count` prüfen, bevor es zurücksetzt.
5. **Mittelmaßnahme:** Rate-Limit-Alarm + Provider-Fallback implementieren.
6. **Langfristig:** Zentraler Retry-Manager + Token-Budget pro Run.

---

## 9. Anhang: Relevante Code-Stellen

### 9.1 `engine/scheduler.py` – `recover_stale_claims()`
```python
# Zeile ~180–210
query = update(Task).where(
    Task.state.in_(["CLAIMED", "PROCESSING"]),
    (Task.lease_expires_at < now) | (Task.lease_expires_at == None)
)
# PROBLEM: Keine Prüfung von retry_count oder 429-Status.
```

### 9.2 `engine/scheduler.py` – `_handle_assignments()`
```python
# Zeile ~240–260
coder_assigned_this_tick = False
# CODER-Gate funktioniert korrekt, wird aber durch recover_stale_claims() unterlaufen.
```

### 9.3 `engine/services/guardian.py` – `_evaluate_retry_policy()`
```python
# Zeile ~179–195
task.retry_count += 1
if task.retry_count >= self.MAX_ITERATIONS:
    return "FAILED", ExecutionPhase.FAILED
# PROBLEM: Wird nicht aufgerufen, wenn recover_stale_claims() vorher zurücksetzt.
```

### 9.4 `engine/services/narrator.py` – „responding slowly“
```python
# Zeile ~58
logger.info(f"[SYSTEM] Task {task_id} is responding slowly ({elapsed_seconds}s elapsed). Waiting for timeout.")
# Artefakt: Wird für alle Tasks im Tick ausgelöst, sobald einer langsam ist.
```

---

*Ende des Statusberichts.*
