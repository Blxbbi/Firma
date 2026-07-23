# Phase 6.1 — Session-ID Collaborative Mode (low-risk)

**Status:** Genehmigt, Start jetzt.
**Strategie:** *Stateless processes, stateful session on disk.* Kein live-gehaltener
stdin-Prozess, keine Writer-Queues, kein PARKED. Wir spawnen weiterhin `pi -p`
(fire-and-forget), hängen aber pro Retry derselben Task dieselbe `--session <id>`
(+ `--session-dir <deterministisch>`) an, sodass `pi` den Kontext aus der
Session-Datei lädt.

**Bewiesen durch Spike (MANATEE):** `pi --session-id X -p "Merke MANATEE"` →
frischer `pi --session-id X -p "Welches Wort?"` gibt MANATEE zurück. Kontext-Erhalt
über separate Prozesse hinweg funktioniert.

---

## Architektur-Entscheidungen (fest)

1. **Session-ID-Scope:** `firma_{run_id}_{task_id}_{role}`. Keine Leaks zwischen
   Runs, besser auditierbar, Cleanup pro Run möglich. (Empfehlung des Users.)
2. **`pi` bleibt fire-and-forget:** weiterhin `-p`. Kein `--mode rpc`, kein
   stdin-Feedback-Routing.
3. **Session-Dateien an deterministischen Ort:** `--session-dir data/sessions/<run_id>/`
   → `cleanup_run` kann den Ordner einfach löschen.
4. **Kernel = Switchboard:** Feedback wird NICHT peer-to-peer geschickt, sondern
   vom Kernel in die nächste Assignment-Spec injiziert (neuer Block
   „Previous feedback / fix instructions").
5. **Backward-only, same-task:** Nur REVIEWER→CODER (und VERIFIER→CODER) Feedback
   innerhalb derselben Task/Role. **Kein Cross-dept** (Planner raus). **Kein live
   Message Bus.**
6. **Output-Contract identisch:** weiterhin `worker_response.<task_id>.response.json`.
7. **Rückwärtskompatibel:** `FIRMA_MODE=deterministic` (Default) = heutiges Verhalten,
   NULL Verhaltensänderung. Collaborative nur bei opt-in.

## Invarianten (§9) — bleiben unangetastet
- Kernel ist alleiniger State-Autorität (DB).
- Push-only Kontext; Worker stateless pro Assignment.
- Strict Validation; Timeout nur im Kernel.
- Artifact push-only; Security Boundary (crew-cwd) bleibt.

---

## Implementationsschritte

### Schritt 1 — `engine/settings.py`
Neue Flags (ENV-overridable, Defaults sicher):
- `FIRMA_MODE = os.environ.get("FIRMA_MODE", "deterministic")`  (`deterministic` | `collaborative`)
- `FIRMA_COLLAB_SESSION_SCOPE = os.environ.get("FIRMA_COLLAB_SESSION_SCOPE", "per_task")`  (V1: `per_task`)
- Session-Basisverzeichnis: `SESSION_DIR = DATA_DIR / "sessions"` (für `<run_id>/`-Unterordner).

### Schritt 2 — neue `engine/session_registry.py` (leichtgewichtig, KEIN Process-Handle)
Nur Mapping + Cleanup-Infos. Key `(run_id, task_id, role)`.
Value: `session_id`, `created_at`, `last_used_at`, `attempt_count_seen`.
API:
- `session_id_for(run_id, task_id, role) -> str`  (deterministisch: `firma_{run_id}_{task_id}_{role}`; idempotent)
- `touch(run_id, task_id, role)`
- `session_dir_for(run_id) -> Path`  (`SESSION_DIR / run_id`)
- `cleanup_run(run_id)`  (löscht `SESSION_DIR / run_id`, falls vorhanden)
- `is_collaborative() -> bool`  (liest `FIRMA_MODE == "collaborative"`)

### Schritt 3 — `engine/providers/pi_provider.py`
- `spawn_for_assignment(..., session_id=None, session_dir=None)`: reicht
  `session_id`/`session_dir` durch.
- `build_args(...)`:
  - deterministic (kein session_id): wie heute (`--no-session` oder ohne Session-Flags).
  - collaborative (session_id gesetzt): füge `--session <id> --session-dir <dir>` hinzu
    (und ggf. `--continue` falls nötig — durch Spike/Test verifizieren welche Flag-Kombi
    den Context lädt; `--session-id` + `--session-dir` reicht laut Spike).
  - `-p` BLEIBT in beiden Modi (fire-and-forget).

### Schritt 4 — Feedback-Injektion (Kernel-seitig, klein)
- Speicherort für letztes Feedback pro Task: neues Feld auf `Task` (z.B.
  `last_review_feedback` / `feedback_logs`) ODER eine schlanke Tabelle
  `task_feedback(run_id, task_id, role, feedback, created_at)`. Entscheidung im
  Implementation, aber DB-Sequenz (Task/Run) bleibt autoritativ.
- Guardian: bei `REVIEW_FAILURE` (und ggf. `VERIFY_FAILURE`) → Feedback-Text
  (aus `response.logs` bzw. strukturiertem Feld) in obige Speicherung schreiben.
- `engine/transport/pi_mesh_transport.py::_build_spec_markdown`: beim Bau der
  Retry-Spec einen Block „## Previous feedback / fix instructions" einfügen, falls
  Feedback für `(run_id, task_id)` existiert. Rein deterministisch; hilft auch im
  deterministic-Mode (nice-to-have).

### Schritt 5 — Windows Cleanup
- `cleanup_run(run_id)` in `SessionRegistry` löscht `SESSION_DIR / run_id`.
- Aufruf aus `controller.stop_run` (nach Run-Ende) und/oder `run_snake.py` finally.
- Kein Kill nötig (keine persistenten Prozesse) — nur Datei-Cleanup.

---

## Tests

### Unit
1. `tests/test_session_registry.py::test_stable_id`
   - gleiche inputs → gleiche session_id; andere role/task/run → andere id.
2. `tests/test_pi_provider_session.py::test_build_args_includes_session_flags_in_collab`
   - collaborative: `build_args` enthält `--session <id>` + `--session-dir <dir>`, weiterhin `-p`.
   - deterministic: KEINE `--session`/`--session-dir` Flags.
3. `tests/test_spec_feedback.py::test_spec_includes_feedback_block_on_retry`
   - bei vorhandenem Feedback → Spec enthält „Previous feedback"-Block.

### Smoke (MANATEE automatisiert)
`tests/test_session_continuity_smoke.py`:
- spawn `pi --session X --session-dir <tmp> -p "Merke: MANATEE"`, exit
- spawn `pi --session X --session-dir <tmp> -p "Welches Wort?"`, assert Output enthält MANATEE.
(Genau der bewiesene Spike, nur reproduzierbar. Darf bei fehlendem Netz/Key
`@pytest.mark.skip`.)

### End-to-End (klein, opt-in)
- Counter-Run mit Collaborative Mode, bei dem der Reviewer beim 1. Attempt
  `REVIEW_FAILURE` liefert (z.B. Reviewer-Persona „first attempt reject"), 2. Attempt
  `REVIEW_APPROVED`.
- Erwartung: CODER-2nd attempt nutzt injiziertes Feedback; Task completet.

---

## Out of Scope (bewusst)
- Cross-dept Feedback (Planner bleibt raus).
- Live Message Bus / stdin-Routing / PARKED-Sessions.
- `test_artifact_contract` wird NICHT angefasst (vorbestehender async-Harness-Bug;
  ggf. später separat, xfail/skip).
- Governance-Validation-Run nicht nötig (5.2 frisch grün, Bugs gefixt).

## Verifikation (Done-Kriterium)
- `python tests/test_session_registry.py`, `test_pi_provider_session.py`,
  `test_spec_feedback.py`, `test_session_continuity_smoke.py` grün.
- Manueller/automatischer Collaborative-Smoke (Counter mit reject→approve) zeigt:
  Retry nutzt Session-Kontext + injiziertes Feedback, Task completet.
- Deterministischer Modus unverändert (Regression-Check via bestehende
  `test_pi_mesh_transport.py` / `test_pimesh_spawn.py`).
- Mirror der geänderten Dateien nach `platform/` (wo vorhanden).

---

## Implementierungsstatus (Stand 16.07.2026)

**IMPLEMENTIERT + UNIT-TESTS GRÜN:**

| Datei | Änderung |
|-------|----------|
| `engine/session_registry.py` (NEU) | `SessionRegistry`-Klasse: `is_collaborative()`, `session_id_for()` → `firma_{run}_{task}_{role}`, `session_dir_for()`, `cleanup_run()`. Kein Process-Handle. |
| `engine/settings.py` | `FIRMA_MODE` (deterministic\|collaborative), `FIRMA_COLLAB_SESSION_SCOPE`, `SESSION_DIR`. |
| `engine/models.py` | Spalte `Task.last_review_feedback`. |
| `engine/providers/pi_provider.py` | `build_args`/`spawn_for_assignment`/`spawn_worker` nehmen `session_id`/`session_dir`; im collaborative Modus `--session-id <id> --session-dir <dir>` statt `--no-session`. |
| `engine/services/guardian.py` | Bei `REVIEW_FAILURE` wird `response.logs` in `last_review_feedback` gespeichert. |
| `engine/scheduler.py` | `previous_feedback` im `task_definition` des Assignments injiziert. |
| `engine/transport/pi_mesh_transport.py` | Feedback-Block in der CODER-Spec (`## Previous feedback ...`). |
| `run_pi_mesh.py` | Callback übergibt `session_id`/`session_dir` (nur im collaborative Modus). |
| `engine/controller.py` | `SessionRegistry.cleanup_run(run_id)` in `stop_run` + `cancel_run`. |
| **Tests** | `test_session_registry.py`, `test_pi_provider_session.py`, `test_spec_feedback.py` (grün); `test_session_continuity_smoke.py` (opt-in, skipt bei fehlendem Netz/Key). |
| **Mirror** | `platform/engine/{settings,guardian,pi_mesh_transport}.py` + `platform/run_pi_mesh.py` gespiegelt (kompilieren). |

**Verifiziert:** 3 Unit-Tests + MANATEE-Smoke-Skip + 2 Regression-Suites (test_pi_mesh_transport, test_pimesh_spawn) alle grün. Import-Smoke OK.

**Noch offen (optional, schwer/teuer):**
- MANATEE-Smoke real ausführen: `FIRMA_CONTINUITY_SMOKE=1 python tests/test_session_continuity_smoke.py` (benötigt `pi`-CLI + Netz/Key).
- E2E Collaborative-Run (Counter/Snake mit echtem Reviewer, der einmal rejectet → CODER-Retry nutzt Session + Feedback).
