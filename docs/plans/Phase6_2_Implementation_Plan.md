# Phase 6.2 — Collaborative Feedback Loop (Proof + Auditability)

**Datum:** 16.07.2026
**Basierend auf:** Phase 6.1 (Session-ID Strategie), `docs/Modi_Collaborative.md`, `docs/Phase6_1_Implementation_Plan.md`

## 0. Kontext / warum 6.2 anders aussieht als ursprünglich

`docs/Modi_Collaborative.md` beschrieb 6.2 ursprünglich als **live Message-Bus +
stdin-Relay in lebendige CODER-Sessions**. Phase 6.1 wurde aber vom User als
**Session-ID Strategie** (stateless processes, stateful session on disk)
ratifiziert — bewusst OHNE live-gehaltene Prozesse/stdin.

Konsequenz: der Kern von 6.2 („Reviewer-Feedback in die CODER-Session relayen")
ist durch 6.1 bereits impliziert: ein Retry spawned einen frischen
`pi --session-id <id>` der den Context aus der Session-Datei lädt, plus das
injizierte `previous_feedback` in der Spec. Ein live Message-Bus ist für V1
(V1 = backward-only, kein Cross-Dept) **nicht erforderlich** und würde das
Windows-Risiko (live stdin) wieder einführen.

**6.2 liefert daher:** (a) einen deterministischen, günstigen **Beweis des
Feedback-Loops** in einem echten Run, (b) **Auditierbarkeit** des Routings.

## 1. Ziel

Beweisen, dass bei `REVIEW_FAILURE` die Kette greift:
`REVIEW_FAILURE` → Guardian speichert `last_review_feedback` → Scheduler injiziert
`previous_feedback` in den CODER-Retry → CODER (neu gespawnt, gleiche Session-ID,
lädt Context von Disk) liest Feedback → fixxt → Dummy/Reviewer approviert →
Task COMPLETE. Und das Ganze auditierbar protokollieren.

## 2. Scope (V1, backward-only)

- Trigger: `FIRMA_REVIEWER_DUMMY_REJECT_ONCE` (env, default off) — nur im
  Dummy-Reviewer-Bypass (wiring-Ebene, kein LLM, deterministisch, günstig).
- Reject genau **einmal pro Task** (erster Review-Versuch), danach APPROVE.
- Keine live Sessions, kein stdin, kein Cross-Dept. Reine Erweiterung von 6.1.
- Deterministischer Modus unverändert (Env off → kein Verhalten).

## 3. Schritte

1. **`engine/settings.py`**: `REVIEWER_DUMMY_REJECT_ONCE` (env
   `FIRMA_REVIEWER_DUMMY_REJECT_ONCE`, default "false", geparst als bool).
2. **`run_pi_mesh.py`** (`make_pimesh_messenger_callback`): im REVIEWER-Dummy-Bypass
   - lokales `rejected_once` Set (pro Run) keyed by `task_id`.
   - wenn `REVIEWER_DUMMY_REJECT_ONCE` und `task_id` noch nicht drin →
     `REVIEW_FAILURE` mit aussagekräftigem `logs` (Feedback) publishen, in Set aufnehmen.
   - sonst (wie bisher) `REVIEW_APPROVED`.
3. **`engine/services/guardian.py`**: bei `REVIEW_FAILURE` → Narrator/Logger
   „Feedback captured for <task>: <first 120 chars>“ (Auditierbarkeit).
   (Speicherung in `last_review_feedback` bereits vorhanden.)
4. **`engine/scheduler.py`**: beim Dispatch mit `previous_feedback` gesetzt →
   Narrator/Logger „CODER retry for <task> carries previous feedback“.
5. **Mirror** nach `platform/run_pi_mesh.py` (+ settings dort).

## 4. Tests

- `tests/test_dummy_reject_once.py`: FakeTransport + FakeProvider, rufe Wrapper
  zweimal (gleiche task_id, steigende state_revision, role=REVIEWER) →
  Assert 1. = `REVIEW_FAILURE`, 2. = `REVIEW_APPROVED`. (Env on)
  + Negativtest (Env off) → beide `REVIEW_APPROVED`.
- Regression: `test_pi_mesh_transport.py`, `test_pimesh_spawn.py`,
  `test_session_registry.py`, `test_pi_provider_session.py`, `test_spec_feedback.py`.

## 5. E2E-Beweis (realer Run)

```
FIRMA_TRANSPORT=pimesh FIRMA_APP=snake FIRMA_MODE=collaborative \
FIRMA_REVIEWER_DUMMY=true FIRMA_REVIEWER_DUMMY_REJECT_ONCE=true \
nohup python run_snake.py > archive/logs/phase6_2_snake.log 2>&1 &
```
Erwartung: pro Task 1× `REVIEW_FAILURE` → Feedback-Capture-Log → CODER-Retry
(Session + Feedback) → `REVIEW_APPROVED` → Task COMPLETE → Run COMPLETED.
Kein Timeout/JSON-Fehler. (Dummy statt echtem Reviewer = deterministisch + günstig.)

## 6. Invarianten (§9) — bleiben intakt

- Kernel alleiniger State-Owner; Worker schreiben nur Artefakte + Response-Datei.
- Push-only, strict validation, artifact push-only, Security Boundary (crew-cwd).
- Session-ID deterministic, scoped `(run, task, role)`; Cleanup via `cleanup_run`.

## 7. Out of Scope (6.2)

- Live Message-Bus / stdin-Relay (durch 6.1 obsolet für V1).
- Cross-Dept `PLAN_REVISION` (erst 6.3).
- Persona/Department-Layer (eigene Ebene, separat).
- Neue DB-Tabelle für Collaboration-Log (Auditierbarkeit via Narrator ausreichend;
  vermeidet Schema-Churn).
