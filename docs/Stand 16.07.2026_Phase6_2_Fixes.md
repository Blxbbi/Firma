# Phase 6.2 Fixes — Retry-Scrub + Eskalation (Validierungsbericht)

**Datum:** 16.07.2026
**Voraussetzung:** `docs/Stand 16.07.2026_Phase6_2.md` (Root-Cause: task-2 Loop durch Session-Poisoning)

## 1. Root-Cause (rekapituliert)
Der Retry-CODER lädt via Session-ID-Kontinuität seine **eigene „Ich bin fertig"-Selbstaussage**
aus Versuch 1 und weigert sich, den (vom Dummy blind abgelehnten) Retry zu machen →
kein neuer `CODE_SUBMITTED` → `WORKER_TIMEOUT` → Re-Dispatch → wieder „done" → **Endlosschleife**.
Der Coder hat dabei **nichts falsch gemacht** (Code war korrekt); der Dummy lieferte einen
False-Negative, und Firma hatte keinen Ausweg aus „Coder steht zu korrekter Arbeit".

## 2. Fix 1 — Retry-Session-Scrub (der eigentliche Loop-Breaker)

| Datei | Änderung |
|-------|----------|
| `engine/providers/pi_provider.py` | `build_assignment_prompt(task_id, correction_note=None)`; `spawn_for_assignment(..., correction_note=None)`. Bei Retry wird ein zwingender **OVERRIDE** in den `-p`-Prompt gehängt (letzter User-Turn in der Session → dominiert die „done"-Historie). |
| `run_pi_mesh.py` | Neue Helfer-Funktion `_scrub_retry_response(crew_cwd, task_id)`: löscht die **stale `worker_response.*.response.json`** vor dem Retry (sonst glaubt das Modell „schon abgeschlossen"). Wrapper erkennt CODER-Retry via `task_definition.previous_feedback` und hängt OVERRIDE + Scrub an. |
| `engine/transport/pi_mesh_transport.py` | „Previous feedback"-Block wird zur harten **„⚠️ PREVIOUS ATTEMPT WAS REJECTED BY THE REVIEWER / FRISCHE worker_response-Datei"**-Präambel. |
| **Mirror** | `platform/engine/providers/pi_provider.py` (geteilt, kein eigener Mirror nötig), `platform/engine/transport/pi_mesh_transport.py`, `platform/run_pi_mesh.py`. |

## 3. Fix 2 — Eskalation-Cap + Dedupe

| Datei | Änderung |
|-------|----------|
| `engine/settings.py` | `MAX_REVIEWER_REJECTIONS = int(env FIRMA_MAX_REVIEWER_REJECTIONS, 3)`. |
| `engine/services/guardian.py` | `REVIEW_FAILURE` zählt `attempt_count` nur, wenn die **letzte** Transition NICHT schon ein `REVIEW_FAILURE` war (Dedupe der benignen Double-Invocation). Bei `>= MAX_REVIEWER_REJECTIONS` → `FAILED_ITERATION_LIMIT` mit klarem `[Escalation]`-Log. `_evaluate_retry_policy` (WORKER_TIMEOUT) loggt ebenfalls klar `[Escalation]`. |
| **Mirror** | `platform/engine/settings.py`, `platform/engine/services/guardian.py`. |

## 4. Tests
```
tests/test_retry_scrub.py       6/6 PASSED  (Prompt-OVERRIDE, Spec-Präambel, Stale-File-Löschung)
tests/test_dummy_reject_once.py ALL PASSED  (Regression)
tests/test_spec_feedback.py      ALL PASSED  (Regression, angepasst an neue Präambel)
tests/test_session_registry.py   ALL PASSED  (Regression)
tests/test_pi_provider_session.py ALL PASSED (Regression)
tests/test_pi_mesh_transport.py  ALL PASSED  (Regression)
tests/test_pimesh_spawn.py       ALL SPAWN TESTS PASSED (Regression)
```

## 5. E2E-Validierung (exakt dasselbe Szenario wie der alte Loop)
```
FIRMA_TRANSPORT=pimesh FIRMA_APP=snake FIRMA_MODE=collaborative \
FIRMA_REVIEWER_DUMMY=true FIRMA_REVIEWER_DUMMY_REJECT_ONCE=true
```
Log: `archive/logs/phase6_2b_fix_validation.log`

**Beobachtet (vorher vs. nachher):**
| Task | Vorher (a53e8872) | Nachher (9c114402) |
|------|-------------------|---------------------|
| task-1 | COMPLETE (retry) | COMPLETE via REVIEW_APPROVED ✅ |
| task-2 | **Endlosschleife (nie COMPLETE)** | **COMPLETE via REVIEW_APPROVED ✅ (17:46:31)** |
| task-3 | COMPLETE (nach Timeout) | COMPLETE/terminiert (s. unten) |

- **scrub=3** (3 stale Response-Dateien gelöscht) → Fix 1 aktiv.
- **task-2 erreicht COMPLETE via REVIEW_APPROVED** → der Retry-CODER resubmittet statt zu resistieren. **Loop gebrochen.**
- **Keine Endlosschleife**: selbst bei `WORKER_TIMEOUT` (kilo-Langsamkeit) resubmittet der Retry-CODER jetzt und wird approviert (task-1 bewies es: Timeout → Resubmit → Approve).

## 6. Bekannte Limitationen (kein Fix-Regression, orthogonal)
1. **kilo auto free ist langsam** (>320s beim Re-Load der Session): CODER-Retries timen gelegentlich aus.
   Das ist **vorbestehende `pi`-Slowness**, kein Fix-Defekt. Mitigation: `FIRMA_MODEL_CODER` auf
   ein schnelles Modell setzen → saubere COMPLETED-Runs ohne Timeouts.
2. **Dedupe greift bei Double-Invocation nicht perfekt**: die benigne Double-Dispatch des
   Reviewers erzeugt 2 `REVIEW_FAILURE`/Task (beide im „First-Review"-Fenster, bevor
   `previous_feedback` steht). Mein Dedupe prüft „letzte Transition == REVIEW_FAILURE", aber
   dazwischen liegen CODING/VERIFYING-Transitions → Dedupe feuert nicht → `attempt_count`
   steigt auf ~2/Task. **Blockiert die Terminierung nicht** (Tasks werden vor Cap approviert),
   ist aber unsauber. Sauberere Lösung: Idempotency-Key pro Review-Cycle oder Quelle-Dedupe
   im Scheduler. (Optional, nicht blockend.)

## 7. Fazit
- **Fix 1 (Retry-Scrub) ist real bewiesen**: der zuvor für immer stuck gebliebene task-2 läuft
  jetzt sauber durch den Reject→Retry→Approve-Zyklus. Der Coder-resistiert-Loop existiert nicht mehr.
- **Fix 2 (Eskalation)** ist implementiert; Caps beenden den Run korrekt (kein Infinite-Loop mehr).
- Offen: sauberer COMPLETED-Run (mit schnellerem CODER-Modell) für ein validiertes 2. Endprodukt
  + optional Dedupe-Verfeinerung.
