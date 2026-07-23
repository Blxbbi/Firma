# PiMesh Workflow — Fließschema (End-to-End)

Wie Firma einen Run über das Worker-Mesh (PiProvider + pi-Subprozesse) von `READY` bis
`COMPLETED` bringt. Alles hier ist aus dem **aktuellen Code** abgeleitet (kein Entwurf).

---

## 0. Zwei Welten: Kernel (State-Sovereignty) vs. Worker-Mesh (stateless)

```
┌──────────────────────────────────────────────────────────────────────┐
│ FIRMA-KERNEL  — alleiniger State-Owner (DB, FSM, Verifier)            │
│   Controller · Orchestrator · Scheduler · Guardian(FSM) ·            │
│   WebStructuralVerifier · PiMeshTransport · PiMeshReceiverLoop ·     │
│   PiProvider · Sqlite-DB                                             │
└──────────────────────────────────────────────────────────────────────┘
        │  dispatch (Datei schreiben) + spawn (Subprocess)
        │  response (Datei lesen + inline + validate)
        ▼
┌──────────────────────────────────────────────────────────────────────┐
│ WORKER-MESH  — 3 Crew-Verzeichnisse, je ein `pi`-Subprozess          │
│   pimesh/planning-crew/   → PLANNER                                   │
│   pimesh/coding-crew/     → CODER                                     │
│   pimesh/reviewing-crew/  → REVIEWER                                  │
│   Jeder Worker ist zustandslos: liest task-N.md, schreibt Dateien +  │
│   worker_response.<id>.response.json, kehrt zurück.                   │
└──────────────────────────────────────────────────────────────────────┘
```

**Golden Rule:** Der Kernel ändert den State. Die Worker lesen eine Spec-Datei und
schreiben Artefakte + eine Response-Datei. Kein Worker ruft je die Firma-DB auf.

---

## 1. Der Tick-Loop (wer ruft wen, im Kreis)

```
Config (run_snake.py: _snake_config / _counter_config)
   │
   ▼
Controller.create_run()  → Run → Project → Plan(v1) → 1 PLANNER-Task(READY, rev 0)
   │
   ▼
Controller.start_run(run_id, messenger_callback)
   │   erzeugt: Transport, Scheduler(mit messenger_callback), Orchestrator
   ▼
Orchestrator.run_forever()  ── alle 0.5s ──▶ Orchestrator.tick()
                                          │
   ┌──────────────────────────────────────┴───────────────────────────────┐
   │ tick():                                                                 │
   │  0. _handle_worker_timeouts()        (HARD 320s → WORKER_TIMEOUT)      │
   │     _handle_verification_phase()     (VERIFYING-Tasks → Verifier)      │
   │  1. Scheduler.run_tick()             (READY→CLAIMED, dann callback)    │
   │  2. transport.poll()                  (Responses aus Queue)             │
   │  3. Guardian.process_response()       (FSM für jede Response)           │
   │  4. _check_run_completion()           (alle terminal? → COMPLETED)     │
   └───────────────────────────────────────────────────────────────────────┘
```

---

## 2. Ein Assignment im Detail (SCHNITTSTELLE Kernel ↔ Worker)

```
Scheduler._handle_assignments()
   │  findet READY-Task im active_plan
   │  assign_task_with_timeout(run, task, 320s)
   │     → DB: state=CLAIMED, state_revision++   (CAS-Schlüssel)
   │
   ▼  asyncio.create_task( messenger_callback(payload) )   ← EINZIGE Auth-Stelle
        payload = {
          event:TASK_ASSIGNMENT, run_id, task_id, role, state_revision,
          prompt: <globaler Projekt-Prompt>,
          task_definition: { description, acceptance_criteria }
        }
   │
   ▼  make_pimesh_messenger_callback(wrapper)
      ├─ [REVIEWER + FIRMA_REVIEWER_DUMMY=true]
      │     → publish_response(REVIEW_APPROVED)  (KEIN Spawn! s. §6)
      │
      └─ [PLANNER / CODER] Normal-Flow:
            a) transport.dispatch(payload)
               → schreibt <crew-cwd>/.pi/messenger/crew/tasks/task-N.json
               → schreibt task-N.md  (VOLLE Spec, siehe §4)
            b) PiProvider.spawn_for_assignment(role, task_id, crew_cwd, model)
               → subprocess.Popen(
                   "pi --mode json --no-session --provider <p> --model <m>
                        --tools read,write,edit,bash --extension <pi-messenger>
                        -p 'Read .pi/messenger/crew/tasks/<id>.md ...'",
                   cwd=crew_cwd, stdout/stderr → .pi/worker.log   )
               → fire-and-forget (kein Warten)
```

### Was der Worker macht (im `pi`-Subprozess, cwd = crew-cwd)
```
  1. liest task-N.md  (die komplette, ungekürzte Spec)
  2. folgt Worker-Vertrag:
       - Dateien schreiben (index.html, style.css, game.js …)
       - worker_response.<task_id>.response.json schreiben   ← Completion-Signal
       - stoppen
  3. stdout/stderr landen in .pi/worker.log  (KEIN Pipe-Deadlock)
```

---

## 3. Response zurück in den Kernel (Receiver → Guardian)

```
Worker schreibt: <crew-cwd>/.pi/messenger/crew/worker_response.<task_id>.response.json
   │
   ▼  PiMeshReceiverLoop.scan_once()  (pollt alle 1s)
      - Datei gefunden?  (Name = task_id ableiten)
      - dedupe: task_id in self._consumed ?  → skip
      - _inline_content(): liest Artefakt-Dateien → artifact.content (inline)
      - Security-Boundary: absoluter Pfad oder ".." → SUBMISSION_INVALID_SCHEMA
      - WorkerResponse.model_validate()  (Pydantic-Schema-Check)
      - self._consumed.add(task_id)
      → transport.publish_response(role, payload, correlation_id=task_id)
   │
   ▼  Orchestrator.tick() Schritt 2: transport.poll()  → message
      envelope-flatten → business_payload
   │
   ▼  Guardian.process_response(session, payload, run_id)
      1. WorkerResponse(**payload)         (Schema-Validierung)
      2. Task existert?
      3. Idempotency-Gate: message_id UNIQUE  → "ALREADY_PROCESSED" bei Dup
      4. Revision-Check:  payload.state_revision == task.state_revision (CAS)
      5. Serialization-Lock: CLAIMED→PROCESSING (rev++)
      6. Role/Event-Auth: GovernanceMatrix.authorize_event(phase, role, event)
      7. FSM: GovernanceMatrix.transition(phase, event) → (next_phase, next_role)
      8. persist_artifacts()  → data/artifacts/<run>/<task>/
      9. transition_task_atomic()  (CAS-Commit, rev++)
```

---

## 4. Datenverträge — was wird wem gegeben

### 4a. PLANNER ← Spec (task-N.md)
```
Global Goal (BACKGROUND ONLY) ....... "Baue eine Snake-Web-App"
Your Task (AUTHORITATIVE) ........... "Erzeuge PlanDraftSchema als JSON"
MUST PASS Acceptance Criteria ....... (Leitplanken für die Tasks)
→ Worker liefert:  plan_draft (PlanDraftSchema)
   = Liste von Tasks {id, description, role:CODER, expected_artifacts, acceptance_criteria}
```

### 4b. CODER ← Spec (task-N.md)
```
Global Goal (BACKGROUND ONLY) ....... Projektkontext
Your Task (AUTHORITATIVE) ........... die eine Teil-Aufgabe + acceptance_criteria
WICHTIG: Verifier/Kernel Acceptance Criteria (MUST PASS) ... EXISTS:/CONTAINS:
→ Worker liefert:  CODE_SUBMITTED + artifacts:[{action:CREATE, path, content}]
   (Datei-basiert; KEIN JSON im Chat, keine canvas/innerHTML-Vorgabe im Prompt)
```

### 4c. VERIFIER (Kernel, Rolle SYSTEM) — liest, schreibt nicht
```
WebStructuralVerifier.verify(session, task_id, project_id, version, artifacts)
   lädt task.acceptance_criteria aus DB
   für jedes Kriterium:
     EXISTS:<path>      → Datei muss in Artefakten vorhanden sein
     CONTAINS:<path>:<s>→ Dateiinhalt enthält s (case-insensitive)
   leer → akzeptiert
→ event: VERIFY_SUCCESS | VERIFY_FAILURE
```

### 4d. REVIEWER
```
Dummy (FIRMA_REVIEWER_DUMMY=true): callback publiziert REVIEW_APPROVED direkt.
Echt (false): PiProvider spawn-t `pi` im reviewing-crew; Worker prüft Code-Qualität
   → REVIEW_APPROVED | REVIEW_FAILURE
```

---

## 5. Die FSM (GovernanceMatrix — Single Source of Truth)

| Aktuelle Phase | Event              | → Nächste Phase  | Nächste Rolle |
|----------------|--------------------|------------------|---------------|
| PLANNING       | PLAN_SUBMITTED     | CODING           | CODER         |
| CODING         | CODE_SUBMITTED     | VERIFYING        | SYSTEM        |
| VERIFYING      | VERIFY_SUCCESS     | REVIEWING        | REVIEWER      |
| REVIEWING      | REVIEW_APPROVED    | COMPLETE         | – (terminal) |
| CODING         | SUBMISSION_INVALID_SCHEMA | CODING     | CODER         |
| VERIFYING      | VERIFY_FAILURE     | CODING           | CODER         |
| REVIEWING      | REVIEW_FAILURE     | CODING           | CODER         |
| * (jede Phase) | WORKER_TIMEOUT     | (wie aktuell)    | (wie aktuell)|
| PLAN_SUBMITTED | (Sonderfall)       | Planner→COMPLETE; neue CODER-Tasks (CODING) | – |

**Iteration-Limit:** `MAX_ITERATIONS = 3`. Bei VERIFY_FAILURE/REVIEW_FAILURE am 3.
Versuch → `FAILED_ITERATION_LIMIT` (terminal, Run = FAILED).

**Completion:** `_check_run_completion()` zählt Tasks mit
`execution_phase NOT IN {COMPLETE, FAILED, FAILED_ITERATION_LIMIT}`. Sind alle
terminal → Run `COMPLETED` (bzw. `FAILED` wenn eine fehlschlug).

---

## 6. Reviewer Dummy-Bypass (Wiring-Ebene, KEIN Kernel-Change)

```
make_pimesh_messenger_callback():
   if role == "REVIEWER" and REVIEWER_IS_DUMMY:
       transport.publish_response(
          REVIEW_APPROVED, sender_role=REVIEWER, artifacts=[])
       return   # ← kein PiProvider.spawn_for_assignment, kein LLM, kein Timeout
```
Ein deterministischer Reviewer, der per Definition APPROVE sagt, ist semantisch
identisch zum in-kernel Verifier (immer-wahr-Check). Sitzt im **Wiring**, nicht im
Kernel → jederzeit via `FIRMA_REVIEWER_DUMMY=false` auf echten LLM umschaltbar.

---

## 7. Invarianten / Guardrails (§9)

| # | Invariante | Wo enforced |
|---|------------|-------------|
| 1 | Kernel State Sovereignty | nur Firma schreibt DB; Worker nur Dateien |
| 2 | Push-only Kontext | Worker bekommt task-N.md, pusht Response-Datei |
| 3 | Stateless per Assignment | Worker hat kein Gedächtnis zwischen Runs |
| 4 | Strict Validation | `WorkerResponse.model_validate` im Receiver |
| 5 | Timeout Kernel-only | `ack_timeout=320s` (Provider-Max 300s + Puffer) |
| 6 | Artifact push-only | Inhalt wird inline im Response mitgeschickt |
| 7 | Security Boundary | absolute Pfade / `..` → `SUBMISSION_INVALID_SCHEMA` |

**Timeout-Policy:** Global 320s/300s wird nicht aufgeweicht. Für einen echten Reviewer
ist das Modell role-spezifisch zu wählen (z.B. `nvidia/meta/llama-3.1-70b-instruct`,
verifiziert ~5s), statt die Governance-Regel zu lockern.

---

## 8. Happy-Path in 8 Schritten (Snake/Counter über PiMesh)

```
1. create_run   → PLANNER-Task READY
2. Scheduler     → CLAIMED + spawn(PLANNER pi)
3. PLANNER       → plan_draft → Guardian: neue CODER-Tasks (READY, CODING)
                   Planner selbst → COMPLETE
4. Scheduler     → pro CODER-Task: CLAIMED + spawn(CODER pi)
5. CODER         → CODE_SUBMITTED + Artefakte → Guardian: VERIFYING
6. Verifier      → EXISTS/CONTAINS-Check → VERIFY_SUCCESS → Guardian: REVIEWING
7. Reviewer      → DUMMY: REVIEW_APPROVED (sofort)
                   ECHT:  spawn(REVIEWER pi) → REVIEW_APPROVED/-FAILURE
8. Guardian      → COMPLETE; _check_run_completion → Run COMPLETED
```

---

## 9. Verzeichnis-Referenz (was liegt wo)

```
Firma-Kernel:
  engine/controller.py        start_run / create_run / stop_run
  engine/orchestrator.py      tick-Loop, _handle_verification_phase, _check_run_completion
  engine/scheduler.py         _handle_assignments (SINGLE authority für Spawn)
  engine/services/guardian.py FSM-Intake + PLAN_SUBMITTED-Sonderfall
  engine/governance.py        GovernanceMatrix (Phase × Event → Next)
  engine/transport/pi_mesh_transport.py  dispatch() / publish_response()
  run_pi_mesh.py              PiMeshReceiverLoop + make_pimesh_messenger_callback
  engine/providers/pi_provider.py        spawn_for_assignment / build_assignment_prompt
  engine/services/verifiers/web_verifier.py  EXISTS/CONTAINS-Verifier

Worker-Mesh:
  pimesh/planning-crew/   .pi/messenger/crew/{agents/crew-worker.md, tasks/, plan.json}
  pimesh/coding-crew/     .pi/messenger/crew/...
  pimesh/reviewing-crew/  .pi/messenger/crew/...
  (jeder Worker schreibt: tasks/task-N.md gelesen, Dateien + worker_response.<id>.response.json)

Persistenz:
  data/db/snake_run_<pid>.db        Run/Tasks/Plans
  data/artifacts/<run_id>/<task>/   finale Artefakte (inline persistiert)
  deliverables/<app>/               kopierte Endprodukte zum Anschauen
```
