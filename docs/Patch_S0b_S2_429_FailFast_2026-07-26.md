# Patch-Set: S0b + S2 — 429 Rate-Limit Fail-Fast
**Datum:** 2026-07-26  
**Betrifft:** `run_pi_mesh.py`, `platform/run_pi_mesh.py`, `engine/services/guardian.py`, `tests/test_receiver_guards.py`  
**Status:** implementiert + getestet

---

## Was wurde gebaut

### S0b: 429-Fail-Fast im Receiver/Bridge
- **Problem:** pi-messenger führt bei `429 "Rate limit exceeded"` interne Auto-Retries durch (3× mit Backoff 2s/4s/8s). Der Kernel wartet 600s auf einen Worker, der bereits „dead in the water“ ist.
- **Lösung:** `PiMeshReceiverLoop` scannt `worker.log` auf 429-Muster und publiziert sofort ein synthetisches `TASK_FAILED` mit `reason: RATE_LIMITED`.

**Dateien:**
- `run_pi_mesh.py` (Root-Entrypoint): `_detect_rate_limit_failure()` + `scan_once()`-Erweiterung
- `platform/run_pi_mesh.py` (Platform-Entrypoint): gleiche Erweiterung

**Detektion:**
- `auto_retry_end` mit `success: false` und `finalError: "429 ..."`
- ODER ≥2× `429 "Rate limit exceeded"` in `message_start`/`message_end`/`turn_end`

**Verhalten:**
- Task wird sofort als `TASK_FAILED` markiert (kein 600s-Timeout mehr)
- Bereits existierende `worker_response.*` wird bevorzugt behandelt (kein Doppel-Feuer)
- Synthetic response bekommt `sender_role: SYSTEM`, `logs: "RATE_LIMITED: ..."`

---

### S2: 429 zählt als Attempt
- **Problem:** `TASK_FAILED` ging bisher durch die Governance-Matrix ohne Retry-Budget-Prüfung (kein `_evaluate_retry_policy`).
- **Lösung:** `TASK_FAILED` mit `logs.startswith("RATE_LIMITED:")` wird durch `_evaluate_retry_policy()` geroutet → `retry_count` wird inkrementiert → bei `>= MAX_ITERATIONS` terminal `FAILED`.

**Dateien:**
- `engine/services/guardian.py`: Zeile ~674, neue Bedingung vor `WORKER_TIMEOUT`-Branch

**Effekt:**
- 429-Stürme verbrauchen jetzt das Retry-Budget (aktuell MAX_ITERATIONS=1)
- Nach 1× Rate-Limited → Task terminal FAILED (kein endloser Retry)

---

## Antworten auf die Berater-Fragen

### 1) Stabile, maschinenlesbare Stelle für 429 in worker.log?
**Ja.**
- `errorMessage: "429 \"Rate limit exceeded\""` in `message_start`/`message_end`/`turn_end`
- `auto_retry_end` mit `success: false`, `finalError: "429 \"Rate limit exceeded\""`
- Beide Patterns werden erkannt.

### 2) Beste Stelle für „Task endgültig failen“?
**`PiMeshReceiverLoop` in `run_pi_mesh.py` / `platform/run_pi_mesh.py`.**
- Der Receiver hat bereits Zugriff auf `worker.log` und publiziert `WorkerResponse`-Events.
- Er publiziert synthetische `TASK_FAILED`-Responses, die der Guardian wie normale Worker-Antworten verarbeitet.
- Vorteil: Keine Änderung am Worker/pi-messenger selbst; liegt vollständig in eurem Code.

---

## Tests

**Neu in `tests/test_receiver_guards.py`:**
- `test_rate_limit_detection_publishes_task_failed` — 429 + auto_retry_end → TASK_FAILED
- `test_no_rate_limit_when_worker_response_exists` — existierende Response schlägt Rate-Limit-Guard

**Ergebnis:** 7/7 Receiver-Guard-Tests grün.

---

## Nächste Schritte (empfohlen)

1. **S1 (optional):** Cooldown/Backoff (`next_eligible_at`) im Scheduler, damit Retries nicht sofort wieder 429en.
2. **S3 (optional):** `recover_stale_claims` prüft `retry_count` vor Reset (aktuell nicht nötig, aber als Defense-in-Depth).
3. **Live-Test:** Run mit aktivem 429-Provider, um zu verifizieren, dass Tasks nach 1× Rate-Limited terminal FAILED werden (nicht erst nach 600s).

---

## Risiko
- **False Positive:** Wenn ein Worker kurzzeitig 429 sieht, aber dann erfolgreich ist, könnte der Receiver zu früh feuern. Aktuell: `auto_retry_end` mit `success: false` oder ≥2× 429 → sehr konservativ.
- **Worker-Log-Pfad:** Der Scan durchsucht `.pi/work/<run_id>/<task_id>/worker.log`. Falls pi-messenger das Format ändert, muss der Parser angepasst werden.
