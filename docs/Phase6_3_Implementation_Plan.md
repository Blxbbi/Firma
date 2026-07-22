# Phase 6.3 — Implementierungsplan: Warm-Base Session Pooling + Personas

> **Status: DRAFT (post-6.2)**
> **Voraussetzung:** Erst umsetzen, wenn **6.1 (Session-ID + Retry-Continuity)** und
> **6.2 (Feedback-Injection + Retry-Scrub + Escalation)** in echten Runs bewiesen sind.
> Dieser Plan ist eine *Vorschrift*, keine sofortige Umsetzung.
> **Leitplanke (siehe §1):** `collaborative` ≠ `session on`. Die Modi werden entkoppelt.
>
> **Status Step 1 (17.07., IMPLEMENTIERT):** `engine/settings.py` (`SESSION_MODE`/`PROCESS_MODE`, Default `off`) + Gate in `run_pi_mesh.py` (`SESSION_MODE != "off"` statt `is_collaborative()`). `pi_provider.build_args` war bereits korrekt (brancht auf `session_id`). Tests: `tests/test_session_mode_gate.py` (green). Default bleibt `off` → bestehende Runs 100% unverändert. Default-Frage (task/persona_base) **bewusst offen**, gestaffelt nach Beweis (s. unten).
>
> **Status 6.3.a persona_base (18.07., IMPLEMENTIERT + UNIT-TESTS GRÜN + E2E BEWIESEN):** `BASE_SESSION_DIR`/`PERSONA_ID` in `settings.py`; `SessionRegistry.base_session_dir_for` + **pi-konformes** atomares `copy_base_to_task` (findet Base-Session `<ts>_base.jsonl`, kopiert, schreibt interne `id` base→target um — pi matched Sessions über interne `id`, nicht Dateiname); cap-aware, Base immutable, kein Bleed, Retry-Continuity erhalten; Gate in `run_pi_mesh.py` seeded bei `SESSION_MODE=persona_base` (Department aus Rolle, Persona aus Config) + **Observability-Log** (department/persona_id/base_dir/task_session_dir/session_id/seeded).
>
> **E2E Counter Run 1** (`session_mode=persona_base`, keine Base): COMPLETED; Gate-Log pro Spawn (department/persona_id/base_dir/task_session_dir/session_id/seeded); session_id stabil pro task/role; Cleanup greift (`data/sessions/<run>` gelöscht); keine Cap-Fallbacks. **E2E Counter Run 2** (mit geseedeter CODER-Base): `seeded=True` für alle 3 CODER-Spawns; Task-Sessions enthalten Base-Kontext (Marker MANATEE aus der Base getragen ✅ → copy-on-start nutzt pi wirklich); Base immutable; Retry nach HARD TIMEOUT (320s) nicht erneut geseedet (Continuity ✅). Terminal-COMPLETED von Run 2 nur durch Free-Model-Latenz verzögert, NICHT persona_base. Tests: `tests/test_persona_base.py` (5 Tests, pi-Session-Format). **3. Commit: nach Snake-E2E (optional) bzw. jetzt möglich.**
>
> **Entscheidung (payload):** `department`/`persona_id` sind (noch) NICHT im Task-Payload. v1 injectet via Settings: `PERSONA_ID` (Default `default`), Department via `ROLE_DEPARTMENT`-Map (PLANNER→planning, CODER→coding, REVIEWER→reviewing). Minimalste Auswahlstrategie; spaeter aus `payload`/`task-N.md` aufloesbar.

---

## 1. Leitplanke — Zwei Achsen statt einem Gate

Heute ist die Session ausschließlich an `FIRMA_MODE=collaborative` gekoppelt
(`run_pi_mesh.py:387` → `if SessionRegistry.is_collaborative():`). Das impliziert
*fälschlicher*: „deterministic = `--no-session`". Für 6.3 (Warm-Base / Personas)
muss das weg.

**Neu — zwei unabhängige Achsen:**

| Achse | Werte | Bedeutung |
|-------|-------|-----------|
| `PROCESS_MODE` | `oneshot` \| `persistent` | Wie lange der `pi`-Prozess lebt. `oneshot` = fire-and-forget (`-p`), `persistent` = live Popen + stdin (alte Collaborative-Resident-Vision, **aktuell NICHT gewünscht**). |
| `SESSION_MODE` | `off` \| `task` \| `persona_base` | Wie Kontext persistiert wird. |

`SESSION_MODE`-Semantik:
- `off` → `pi ... --no-session` (maximal strikt, CI).
- `task` → `--session-id firma_{run}_{task}_{role}`, `session_dir` pro Run (Retry-Continuity).
- `persona_base` → Base-Session pro `(department, persona_id)` wird vorgehalten und per **copy-on-start** in die Task-Session kopiert (Warm-Start, keine Live-Loops).

**Zulässige Kombinationen (Beispiele):**
- `deterministic + oneshot + task` → Retry-Continuity, aber keine Live-Chat-Loops.
- `deterministic + oneshot + persona_base` → **Warm-Start ohne Kollaboration** (6.3.a).
- `collaborative + oneshot + task (+ feedback-injection)` → Reviewer→Coder-Loop über Specs (heutiger 6.1/6.2-Pfad).

Determinismus bleibt *relativ* erhalten: kein Live-Routing, deterministische Inputs,
one-shot Prozesse. Nur „deterministic = ohne Session" wird zu „deterministic = one-shot
Prozess + deterministische Inputs + kein Live-Routing" **reframed**.

---

## 2. Ist-Zustand (Fundstellen)

| Entscheidung | Datei:Zeile | Funktion |
|---|---|---|
| Session-ID-Konstruktion | `engine/session_registry.py:32` | `session_id_for(run_id, task_id, role)` → `f"firma_{run_id}_{task_id}_{role}"` |
| Pro-Run Session-Dir | `engine/session_registry.py:41-43` | `session_dir_for(run_id)` → `SESSION_DIR / run_id` |
| Basis-Pfad | `engine/settings.py:29` | `SESSION_DIR = DATA_DIR / "sessions"` |
| Gate (nur collaborative) | `run_pi_mesh.py:386-390` | `if SessionRegistry.is_collaborative(): session_id = ...` |
| Flag-Emission | `engine/providers/pi_provider.py:71-73` | `build_args`: `--session-id/--session-dir` **oder** `--no-session` |
| Worker-Spawn | `engine/providers/pi_provider.py:107/135/144` | `spawn_for_assignment → spawn_worker → build_args → Popen` |
| Spec-Render (Persona-Hook) | `engine/transport/pi_mesh_transport.py:129` | `_build_spec_markdown(payload, ...)` |

**Kritisch:** Im Default (deterministic) ist `session_id=None` → `build_args` emittt
`--no-session`. Die validierten Runs (99b9f0e6, 609f0c95) liefen OHNE Disk-Session;
der 6.2-Feedback-Loop läuft über die Spec (`previous_feedback`-Block), nicht über die
Session-Datei. 6.3.a braucht Sessions also **auch außerhalb collaborative**.

---

## 3. 6.3.a — Warm-Base Session Pooling (Option A, disk-basiert)

### 3.1 Base-Session Layout
```
data/sessions/
  _base/<department>/<persona_id>/      # read-only Quelle (Regel A2)
  <run_id>/<task_id>/<role>/            # Task-Session (Worker schreibt hier)
```

### 3.2 Regel A1 — Base enthält KEINE Task-Outputs
Base darf NUR enthalten:
- Stack / Conventions („wir bauen Web-Apps so…")
- Output-Contract (Dateinamen, Enums, Pfad-Regeln)
- Repo-Konventionen (File-Naming, Style)

Base darf **nie** fertigen Code eines konkreten Tasks enthalten.

### 3.3 Regel A2 — Base ist write-protected
- `copy_base_to_task(base_dir, task_dir)` kopiert bei Task-Start; Worker schreibt NUR in `task_dir`.
- Base-Dir wird **read-only** markiert (Windows: `attrib +R`, best-effort; in Code erzwingen: nie in Base spawnen).
- Optionale ACL-Absicherung, falls verfügbar.

### 3.4 Copy-on-start — atomar + begrenzt (Zusatz-Regeln)
- **Atomar:** zuerst in temp-Dir kopieren, dann `rename()` (sonst liest `pi` halb-kopierte Sessions).
- **Size-Cap:** vor Copy `MAX_SESSION_DISK_MB_PER_RUN` prüfen; bei Überschreitung **failsafe** zurück auf `SESSION_MODE=task` (oder `off`), nicht crashen.
- **Idempotent:** erneuter Versuch derselben Task (Retry) nutzt wieder die *Task*-Session (nicht Base) → Retry-Continuity aus §1 bleibt erhalten.

### 3.5 SessionRegistry-Key (Erweiterung)
- `base_session_dir_for(department, persona_id)` → `data/sessions/_base/<department>/<persona_id>/`
- `task_session_dir_for(run_id, task_id, role, department, persona_id)` → abgeleitet.
- Key wird `(department, persona_id, role)` → liefert Base-Pfad + abgeleitete Task-Session.

---

## 4. 6.3.c — Persona / Department-Layer (minimal, robust)

### 4.1 Persona im Task-Spec
In `task-N.md` (bzw. `payload`):
```
persona_id: anton        # oder "default"
department: planning|coding|reviewing
```
Kein FSM-Wechsel nötig — Auswahl per ENV / Run-Config (`Snake = anton`, `Landingpage = paul`).

### 4.2 Auswahl-Mechanik
- `run_pi_mesh.py`: statt `models.get(role)` → `(department, persona_id)`-Schlüsselung für Modell + Base-Session.
- `SessionRegistry.session_id_for` nutzt `(department, persona_id, role, task_id)`.
- `_build_spec_markdown` rendert `persona_id`/`department` aus `payload` in die Worker-Spec.

### 4.3 Roster (minimal, später)
`available: true/false` pro Persona → Routing nur an verfügbare. (Vollständiges Roster ist optionaler Mehrwert, kein Blockierer für 6.3.c.)

---

## 5. Caps & Cleanup
- `MAX_SESSION_DISK_MB_PER_RUN` (einfacher Guard, s. §3.4).
- `MAX_BASE_SESSIONS` (klein, z.B. 10).
- **Cleanup am Run-Ende:** Task-Sessions löschen (`SessionRegistry.cleanup_run`), Base bleibt erhalten.
- Disk-Pooling kann auch ohne resident processes ausufern → Caps sind MUST.

---

## 6. Touch-Points (Refactor-Dateiliste)

| # | Datei | Änderung |
|---|-------|----------|
| 1 | `engine/settings.py` | `PROCESS_MODE`, `SESSION_MODE`, `MAX_SESSION_DISK_MB_PER_RUN`, `MAX_BASE_SESSIONS`, `BASE_SESSION_DIR` (neu). `FIRMA_MODE` bleibt für Routing/Loop-Semantik. |
| 2 | `engine/session_registry.py` | `base_session_dir_for`, `task_session_dir_for`, `copy_base_to_task` (atomic+cap). Key `(department, persona_id, role, task_id)`. |
| 3 | `run_pi_mesh.py:386-399` | Gate `is_collaborative()` → `if settings.SESSION_MODE != "off":`. Immer `session_id/session_dir` setzen (außer `off`). Vor Spawn `copy_base_to_task`. `persona_id` aus Spec. |
| 4 | `engine/providers/pi_provider.py:build_args` | `SESSION_MODE=off` → `--no-session`; sonst `--session-id/--session-dir`. `session_dir` ggf. `mkdir`. |
| 5 | `engine/transport/pi_mesh_transport.py:_build_spec_markdown` | `persona_id`/`department` aus `payload` rendern. |
| 6 | Tests (neu) | s. §8. |

---

## 7. Staging (Reihenfolge)
1. **6.1 (klein, schnell):** `SESSION_MODE=task` nur für collaborative; Feedback-Injection für Retries; Smoke „Reviewer rejects first → Coder retry nutzt gleiche Session-ID".
2. **6.2 (stabilisieren):** Dedupe / Retry / Session-Cleanup pro Run; Session-GC.
3. **6.3.a (danach):** copy-on-start + Persona-Selection + Disk-Caps + Immutability (mehr moving parts).

---

## 8. Tests

### Unit
1. **Base is immutable** — simuliere „Task-Session schreibt", assert Base-Files unverändert.
2. **Copy-on-start correctness** — nach Start existiert Task-Session, enthält Base-Inhalt; atomar (temp+rename).
3. **Size-cap failsafe** — bei Überschreitung fällt `persona_base` sauber auf `task`/`off` zurück.
4. **Persona selection** — `persona_id=anton` → Base-Dir von Anton, nicht Paul.

### E2E Smoke (Bleed-Test)
- Run mit 3 CODER-Tasks:
  - Task1 erzeugt bewusst Marker im Session-Memory („remember X").
  - Task2 (neue Task-Session aus Base) darf **nicht** X sehen.
  - **Proof:** kein cross-task memory bleed (Regel A1/A2 wirksam).

---

## 9. MUST / SHALL (Anforderungen)
- **MUST** `SESSION_MODE != "off"` erlaubt Sessions unabhängig von `FIRMA_MODE`.
- **MUST** Worker schreiben ausschließlich in Task-Session, nie in Base.
- **MUST** copy-on-start ist atomar (temp+rename) und cap-geprüft mit failsafe.
- **MUST** Cleanup löscht Task-Sessions, behält Base.
- **SHALL** `PROCESS_MODE=oneshot` bleibt Default (kein resident process in 6.3).
- **SHALL** Determinismus bleibt erhalten (kein Live-Routing, deterministische Inputs).
- **SHALL** `SESSION_MODE=off` bleibt als strikte CI-Option bestehen.

---

## 10. Out of Scope (später)
- **6.3.b Cross-Dept / Message-Bus:** opt-in, FSM-Erweiterung `PLAN_REVISION`, strenge Governance. Erst nach 6.3.a+c.
- **`PROCESS_MODE=persistent`:** residente Sessions + Bus (alte Collaborative-Resident-Vision). Risiko: Lifecycle, Tokens, weniger Reproduzierbarkeit.
- **Vollständiges Roster** mit Join/Leave.

---

## 11. Offene Fragen
- Soll `SESSION_MODE` Default künftig `task` (statt `off`)? (Empfehlung: `off` bleibt Default, explizit einschalten.)
- Base-Sessions: pro Run neu aufbauen oder persistent über Runs cachen? (Empfehlung: persistent, da „Warm" der Nutzen ist.)

---

## 12. Resident Mode (`PROCESS_MODE=persistent`) — deferred, erklärt

### 12.1 Was es ist
Anstatt den Worker-Prozess nach jedem Task zu killen (oneshot), bleibt `pi` am
Leben: **stdin offen**, stdout als JSONL-Stream gelesen. Neue Turns/Task werden als
Nachricht in die **stdin** geschrieben (Message-Bus `route(target, message)`). Das
Modell hält seinen **KV-Cache warm im lebenden Prozess** → kein Reload von Disk.

Das ist exakt das Design aus `docs/Modi_Collaborative.md` §3: `SessionHandle` mit
`proc: subprocess.Popen`, offenem stdin, stdout→`worker.log`. „Nur wenn was kommt
schreiben" = event-gesteuertes stdin-Feed via Bus.

### 12.2 Disk-Session vs. Resident — der Unterschied
- **Disk-Session (oneshot, unser Modell):** Prozess tot → KV-Cache weg. Frischer Spawn
  liest Session-**Datei** (Transcript), schickt **ganze History als Input** an die API,
  Modell **re-attended von vorne** (full prefill). Context wird „von null neu geladen".
- **Resident (persistent):** Prozess lebt, KV-Cache warm. Neuer Turn wird direkt
  verarbeitet, **ohne** Disk-Reload. Context ist „echt warm".

### 12.3 „Nie auf Disk" — Korrektur
Selbst resident schreibt man auf Disk: Artefakte, `worker.log` (Audit), und ein
Session-Backup für Crash-Recovery (abgestürzter residener Worker = sonst total verloren;
`pi` persistiert i.d.R. ohnehin seine Session). Unterschied: der Konversations-State
lebt im Prozess, wird **nicht pro Turn neu von Disk geladen**.

### 12.4 Preis/Leistung
| | Disk-Session (oneshot) | Resident (persistent) |
|---|---|---|
| Input-Tokens pro Call | Volle History jedes Mal bezahlt (re-prefill) | Prefix gecached → billig (falls Provider cached) |
| KV-Cache | Weg (Prozess tot) | Warm |
| Output-Tokens | Gespart (History da) | Gespart |
| Latenz | Full prefill jedes Mal (Teil des „responding slowly") | Schneller (nur neuer Turn) |
| Lifecycle | Trivial (Prozess endet) | Bus + Idle-Timeout + Crash-Recovery nötig |

**Free-Tier-Realität:** Auto-Router (`tencent/hy3:free`) cached i.d.R. **nicht** →
resident spart hier v.a. **Latenz + Cold-Start**, aber **kaum Tokens** (API kriegt
volle History trotzdem). Token-Vorteil von resident zeigt sich erst bei cached Modellen
(z.B. bezahlte Anthropic/OpenRouter).

### 12.5 Warum deferred (Risiko)
- Lifecycle-Komplexität (Idle-Kill, Crash, Windows-PID-Shim).
- N offene LLM-Contexts (Memory/Kosten).
- Weniger deterministisch/reproduzierbar.
- Crash-Fragilität (in-process State weg; Disk ist robuster).
→ Eigenständiger, invasiverer Sprint (`Modi_Collaborative.md` §3: Popen offen halten
+ `route()` + Idle-Timeout). **Nicht Teil von 6.3.a.**

### 12.6 Entscheidung
Resident = das „wirklich fortschrittlichste", aber als **6.3.b / später, opt-in**.
`persona_base + oneshot` (6.3.a) holt den Großteil des Speed-Gewinns **OHNE** live
Prozesse. 6.3.a ist bewusst „warm via Disk-Copy, Prozess stirbt trotzdem".
