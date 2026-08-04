# Erratum zum Statusbericht Retry/Provider/Tokenverbrauch
**Datum:** 2026-07-26 (korrigierende Ergänzung)  
**Betrifft:** `docs/Statusbericht_Retry_Provider_Tokenverbrauch_2026-07-26.md`

---

## Korrektur zu Abschnitt 4 (Root-Cause-Analyse)

### Vorherige Hypothese (zurückgezogen)
> "`recover_stale_claims()` unterläuft `retry_count` und erzeugt einen Kernel-Respawn-Loop."

### Korrigierte Befunde
- **Kein Kernel-Respawn-Loop.** Die Spawn-Logs zeigen für `task-4` nur **1 Kernel-Spawn** (14:49:16).  
- **Keine wiederholten `recover_stale_claims`-Aufrufe** für diesen Run nachweisbar.  
- `retry_count` wurde sehr wohl inkrementiert: `task-4` endete mit `retry_count: 1/1` (MAX_ITERATIONS=1).  
- Die 86× `turn_start` sind **Turns in einem einzigen Worker-Prozess**, keine Spawns.  

### Echte Root Cause
Das Problem liegt in der **Kombination zweier Schleifen-Systeme**:
1. **Kernel-Loop:** Scheduler/Guardian mit Retry/Timeout-Budget.
2. **pi/Worker-internal-Loop:** pi-messenger/Agent führt bei `429 "Rate limit exceeded"` interne Auto-Retries durch (3× mit Backoff 2s/4s/8s), **ohne dass der Kernel davon weiß**.

Der Kernel wartet deterministisch bis zum 600s-Timeout, während der Worker intern bereits hängt. Das verbraucht Zeit und sehr wahrscheinlich Tokens auf der Provider-Seite.

---

## Korrektur zu Abschnitt 6 (Lösungsvorschläge)

### Zurückgestellt
- Option A/C (`recover_stale_claims` anpassen) ist **nicht die erste Maßnahme**, weil kein Kernel-Respawn-Loop vorliegt.

### Priorisierte Maßnahmen (korrigiert)
1. **S0b (sofort):** 429-Detektion im Receiver/Bridge → sofort `TASK_FAILED` mit `reason: RATE_LIMITED` publizieren + Prozess beenden.
2. **S2 (sofort):** `TASK_FAILED` mit `reason: RATE_LIMITED` zählt als `attempt` und durchläuft das Retry-Budget (`_evaluate_retry_policy`).
3. **S1 (optional):** Cooldown/Backoff (`next_eligible_at`) im Scheduler, damit Retries nicht sofort wieder 429en.

---

## Ausblick
Die nächsten Patches zielen auf **S0b + S2** ab. Sobald sie implementiert sind, wird ein neuer Statusbericht die Wirksamkeit belegen.
