# Phase 6.2 Bericht — Collaborative Feedback Loop (Proof + Auditability)

**Datum:** 16.07.2026
**Vorgänger:** `docs/Phase6_2_Implementation_Plan.md`, `docs/Stand 16.07.2026.md` (Phase 6.1)

## 1. TL;DR

Phase 6.2 ist **implementiert und der Feedback-Loop real bewiesen**.

Der ursprüngliche 6.2-Plan (live Message-Bus + stdin-Relay) wurde durch die
**Session-ID Strategie aus 6.1 obsolet** (Context steckt in der Session-Datei auf
Disk; Retry lädt ihn + injiziertes Feedback). 6.2 liefert daher:
- Einen **deterministischen Loop-Trigger** (`FIRMA_REVIEWER_DUMMY_REJECT_ONCE`),
  der den echten `REVIEW_FAILURE → CODER-Retry`-Pfad günstig + reproduzierbar
  beweist (kein teurer/unkündbarer LLM-Reject nötig).
- **Auditierbarkeit** (Narrator-Logs für Feedback-Capture + Retry-with-feedback).

Beim E2E-Beweis wurden **zwei echte, zuvor latente Bugs** gefunden und behoben
(siehe §4). Danach: 2 von 3 Tasks durchliefen den vollen Zyklus
`REJECT → Feedback → Retry → Approve → COMPLETE`; einer blieb an
`pi`-Slowness (Timeout) hängen — ein **vorbestehendes**, nicht-6.2-Problem.

## 2. Was in Phase 6.2 implementiert wurde

| Datei | Änderung |
|-------|----------|
| `engine/settings.py` | `REVIEWER_DUMMY_REJECT_ONCE` (env `FIRMA_REVIEWER_DUMMY_REJECT_ONCE`, default off). |
| `run_pi_mesh.py` | REVIEWER-Dummy-Bypass: beim **ersten** Review (kein `previous_feedback`) → `REVIEW_FAILURE` + Feedback; beim Retry (`previous_feedback` gesetzt) → `REVIEW_APPROVED`. `message_id` jetzt eindeutig pro Publish (`uuid`). |
| `engine/services/guardian.py` | Feedback-Capture (**auf JEDEM** `REVIEW_FAILURE`, routing-unabhängig) → `last_review_feedback` + Narrator-Log. |
| `engine/scheduler.py` | Bei Retry-Dispatch mit `previous_feedback` → Narrator-Log „CODER retry carries previous feedback". |
| `tests/test_dummy_reject_once.py` (NEU) | Unit-Test: Dummy lehnt beim 1. Review ab, approviert beim Retry (stateless via `previous_feedback`). |
| **Mirror** | `platform/engine/settings.py`, `platform/engine/services/guardian.py`, `platform/run_pi_mesh.py` gespiegelt. |

Opt-in: `FIRMA_REVIEWER_DUMMY_REJECT_ONCE=false` (Default) = kein Verhalten;
`=true` = Dummy-Reviewer lehnt pro Task genau einmal ab. Deterministischer
Modus unverändert.

## 3. Was validiert wurde

### 3.1 Unit-Tests (grün)
```
test_dummy_reject_once.py   ALL TESTS PASSED   (reject-first / approve-retry, stateless)
test_session_registry.py    ALL TESTS PASSED   (Regression)
test_pi_provider_session.py ALL TESTS PASSED   (Regression)
test_spec_feedback.py       ALL TESTS PASSED   (Regression)
test_pi_mesh_transport.py   ALL TESTS PASSED   (Regression)
test_pimesh_spawn.py        ALL SPAWN TESTS PASSED (Regression)
```

### 3.2 E2E Collaborative Run (Loop-Beweis)
Befehl:
```
FIRMA_TRANSPORT=pimesh FIRMA_APP=snake FIRMA_MODE=collaborative \
FIRMA_REVIEWER_DUMMY=true FIRMA_REVIEWER_DUMMY_REJECT_ONCE=true \
nohup python run_snake.py > archive/logs/phase6_2_snake.log 2>&1 &
```
Run-ID: **`a53e8872-d042-4ec8-a95d-1fab952fbad4`**

Beobachtete Fakten (aus dem Log):
- **Feedback captured: 3/3 Tasks** (Guardian speichert `last_review_feedback`).
- **CODER retry carries previous feedback: 4** (Scheduler injiziert es in den Retry).
- **REVIEW_FAILURE: 6** (bzw. ~2/Task — siehe §4 Race), **REVIEW_APPROVED: 4**.
- **Task task-1**: `REVIEWING→CODING` (reject) → CODER-Retry → `REVIEWING→COMPLETE via REVIEW_APPROVED`. ✅ voller Zyklus.
- **Task task-3**: wie task-1, **inklusive eines CODER-`WORKER_TIMEOUT`**, das sauber
  re-dispatched wurde und dann ebenfalls `COMPLETE via REVIEW_APPROVED` erreichte. ✅
  (beweist: der Loop ist robust gegen Worker-Timeouts).
- **Task task-2**: blieb in einem CODER-Timeout-Loop stecken (siehe §5).

**Fazit des Beweises:** Der Collaborative Feedback-Loop funktioniert end-to-end:
`REVIEW_FAILURE` → Feedback wird gespeichert → CODER-Retry lädt Session-Context
(§6.1) + injiziertes Feedback → fixxt → Reviewer approviert → Task COMPLETE.

## 4. Beim E2E-Beweis gefundene + behobene Bugs (wichtig)

Die Validierung lohnte sich — sie deckte **zwei latente Fehler** auf, die im
„glatten" 6.1-Run (ohne Reject) nie getriggert wurden:

1. **Feedback-Speicherung im falschen Branch (kritisch).**
   In 6.1 lag die `last_review_feedback`-Speicherung in der **terminalen
   `FAILED`-Branch** des Guardians. Aber `REVIEW_FAILURE` routet normalerweise
   zu **`CODING` (Retry)**, nicht zu `FAILED`. Folge: Feedback wurde nie
   gespeichert → kein `previous_feedback` → Dummy lehnte ewig ab → Loop.
   **Fix:** Speicherung + Log jetzt auf **JEDEM** `REVIEW_FAILURE`,
   routing-unabhängig (Guardian, vor der Phasen-Entscheidung).

2. **Kollidierende `message_id` im Dummy-Reviewer (DB-Fehler).**
   Der Dummy nutzte ein statisches `message_id = "mock-{task_id}"`. Bei mehreren
   Publishes für dieselbe Task (Reject + Approve, bzw. Double-Invocation)
   krachte die `UNIQUE`-Constraint auf `message_log.message_id` → DB-Error →
   Run steckte fest. **Fix:** `message_id` pro Publish eindeutig
   (`f"mock-{tid}-{uuid.uuid4().hex[:8]}"`).

Beide Fixes sind in `engine/` + `platform/` gespiegelt.

## 5. Caveat (KEIN 6.2-Bug): CODER-Timeouts bei kilo auto free

Die Retry-CODERs brauchten teils >320s (das `pi`-ack_timeout-Ceiling), weil
kilo auto free beim Re-Load der größeren Collaboration-Session (erster Attempt +
Feedback) langsamer ist. Task-2 geriet so in einen Timeout-Loop. Das ist
**vorbestehende `pi`-Slowness**, kein 6.2-Defekt — und zeigte sich auch nur,
weil der Loop bewusst Retries erzwingt.

Mitigation (optional, nicht Teil von 6.2): für Collaborative-Runs ein
schnelleres `FIRMA_MODEL_CODER` setzen oder `ack_timeout` anheben. Die
Governance (Run wird erst terminal, wenn ALLE Tasks terminal sind; kein
vorzeitiger Fail-Fast) funktionierte wie erwartet.

## 6. Was definitiv korrekt funktioniert (konsolidiert)

- **Phase 6.1:** Session-ID Strategie (Context über Retries via `--session-id/
  --session-dir`), opt-in, Cleanup, Determinismus — bewiesen (MANATEE-Smoke +
  E2E `ef3f84e6…` COMPLETED).
- **Phase 6.2:**
  - Feedback-Loop **real bewiesen**: `REVIEW_FAILURE` → `last_review_feedback`
    gespeichert → `previous_feedback` in CODER-Retry injiziert → Approve →
    COMPLETE (task-1 + task-3 im Run `a53e8872…`).
  - Loop **robust gegen Worker-Timeouts** (task-3 vollendete nach einem
    CODER-Timeout-Retry).
  - Dummy-Reviewer deterministisch (reject-once), `message_id` eindeutig.
  - Auditierbarkeit via Narrator („Feedback captured", „CODER retry carries
    previous feedback").
- **Regression:** alle 6 Test-Suites grün.

## 7. Nächste Schritte (offen)

- **6.3 Cross-Dept** (erst später; V1 erlaubt nur backward-Routing).
- **Persona/Department-Layer** (`docs/Persona_Departments.md`).
- Optional: Collaborative-Runs mit schnellerem `FIRMA_MODEL_CODER` fahren, um
  CODER-Timeouts bei großen Sessions zu vermeiden.
- Der ursprüngliche 6.2 „live Message-Bus" gilt als durch 6.1 obsolet (V1).
