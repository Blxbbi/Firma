# Stand 18.07.2026 — Firma Session-Achsen (Phase 6.3)

**Thema:** Entkopplung der Session-Strategie von `FIRMA_MODE`, plus Warm-Base (`persona_base`) mit
copy-on-start. Alles E2E bewiesen, committet + getaggt.

**Branch:** `chore/clean-architecture`

---

## 1. Überblick

Wir haben die Session-Strategie in **zwei unabhängige Achsen** reframt:

- `SESSION_MODE` (off | task | persona_base) — *ob/wie* Sessions genutzt werden.
- `PROCESS_MODE` (oneshot | resident) — *wie* der Worker läuft.

Default bleibt `SESSION_MODE=off` (== heutiges deterministices Verhalten, `--no-session`).
`FIRMA_MODE=collaborative` schaltet Sessions **nicht meer automatisch** an — wer Sessions
will, setzt `FIRMA_SESSION_MODE` explizit. Keine Magie, stabile Defaults.

Drei Bausteine, jeder ein eigener, reviewbarer Commit + grüner Tag:

| # | Commit | Inhalt | Beweis |
|---|---|---|---|
| 1 | `7624899b` | Gate-Entkopplung `SESSION_MODE` / `PROCESS_MODE` | Unit-Tests grün |
| 2 | `6a688c33` | `SESSION_MODE=task` + Disk-Cap + Cleanup | Unit + E2E-Run `8df1622c` |
| 3 | `674f3c54` | `persona_base` Warm-Base copy-on-start (pi-konform) | Unit + 2× Counter-E2E |

**Tags:** `phase6-step2-e2e-proven`, `phase6-step3-persona_base-e2e-proven`

---

## 2. Probleme & Lösungen

### A. Magie-Kopplung (Session an FIRMA_MODE)
`FIRMA_MODE=collaborative` schaltete Sessions automatisch an → verletzt „keine Magie / stabile
Defaults".
**Lösung:** `SESSION_MODE` als eigene Achse; Gate `if SESSION_MODE != "off":`. Default `off`
== heute. `is_collaborative()` bleibt nur für Tests erhalten.

### B. Unkontrolliertes Disk-Wachstum
Sessions wachsen pro Run; ohne Grenze Risko von Disk-Full.
**Lösung:** `MAX_SESSION_DISK_MB_PER_RUN` (Default 200, `0`=aus). Bei Überschreitung
spawnt das Gate **fail-safe OHNE Session** (kein Crash, keine unkontrollierte Growth).
Cleanup am Run-Ende war bereits in `controller.py` verdrahtet (bewiesen in Step 2).

### C. KRITISCH — pi lädt Sessions über interne `id`, nicht den Dateinamen (nur via E2E gefunden)
Der erste `copy_base_to_task` benannte die Base-Datei `"base"` → `<target>` um. Funktioniert im
Unit-Test (hand-benannte Datei), **aber nicht mit echtem pi**:

- pi speichert Sessions als `<timestamp>_<session-id>.jsonl`
  (z. B. `2026-07-17T22-40-08-960Z_base.jsonl`).
- pi **matched beim Laden über das Feld `"id"` in der ersten JSONL-Zeile**, nicht über den Dateinamen.
- Ein rein umbenannter File (`…_testXYZ.jsonl`, interne `id` blieb `"base"`) wurde von pi
  **ignoriert** → frische Session.

**Lösung (pi-konform):** `copy_base_to_task` findet die Base-Session (`*_base.jsonl` oder
interne `id=="base"`), kopiert sie in `task_dir` und **schreibt die interne `id` von `base`
auf `<target>` um**, damit pi den Warm-Context über `--session-id <target>` lädt. Verifiziert
durch Resume-Test: nach dem Umschreiben erinnerte pi sich an den Base-Kontext.
Unit-Tests auf das echte pi-Format umgestellt.

### D. Free-Model-Latenz / Hard-Timeout (orthogonal zu persona_base)
Im Counter-Run 2 timten alle 3 CODER-Tasks **gleichzeitig nach exakt 320s** aus.
Forensik (Coding-Worker-Log) zeigte: Modell = `tencent/hy3:free` (via Auto-Router
`kilo-auto/free`), das im 00:45-Fenster langsam/congestioniert war. `cacheRead:15232` beweist:
die geseedete Base **wurde geladen und genutzt** (kein Parse-Fehler). Der **Retry auf derselben
Base** (mehr Context!) lief in ~46s durch → beweist: die Base hat die Completion **nicht**
blockiert. Ursache = Free-Model-Latenz-Varianz (bekannt aus 5.2/6.1/6.2), nicht persona_base.
Die Retry-Resilienz der Engine hat den Run gerettet.

---

## 3. Was E2E bewiesen ist

### Step 2 — `SESSION_MODE=task` (Run `8df1622c`)
- Reviewer-REJECT-ONCE → CODER-Retry nutzt **dieselbe `session_id`** (Retry-Continuity).
- `session_mode=task` in allen Spawn-Logs.
- Sessions nach Run-Ende gelöscht (Cleanup greift).

### persona_base — Run 1 (Counter, `session_mode=persona_base`, **keine** Base)
- Run `COMPLETED` (~2 min).
- Gate-Log pro Spawn: `department` / `persona_id` / `base_dir` / `task_session_dir` / `session_id` / `seeded`.
- `session_id` stabil pro task/role.
- Cleanup greift (`data/sessions/<run>` gelöscht). Keine Cap-Fallbacks.

### persona_base — Run 2 (Counter, mit **geseedeter** CODER-Base)
- `seeded=True` für alle 3 CODER-Spawns → Real-Copy greift.
- Task-Sessions enthalten den Base-Kontext (Marker **MANATEE** aus der Base getragen ✅) →
  copy-on-start nutzt pi wirklich.
- Base **immutable** (Base-Datei unverändert).
- Retry nach HARD TIMEOUT (320s) **nicht** erneut geseedet (Continuity erhalten).

> Hinweis: Run 2 erreichte terminal `COMPLETED` nur verzögert (Free-Model-Latenz), nicht
> wegen persona_base. Der Mechanismus ist eindeutig bewiesen.

---

## 4. Was es uns bringt

- **Determinismus + Observability:** Jeder Spawn loggt explizit, welche Session-Strategie greift und warum.
- **Warm-Base ohne Pollution:** Persona-Kontext wird nur als *Copy* in die Task-Session injiziert;
  die Base selbst bleibt heil (einmalige Seed-Quelle).
- **Fail-Safe by Design:** Disk-Cap, No-Crash-Fallbacks, Retry-Continuity — robust gegen Free-Model-Ausfälle.
- **Saubere Historie:** Jeder Schritt = eigener, reviewbarer Commit mit grünem Tag → jederzeit stabiler Stand.

---

## 5. Wo wir stehen (Git / Tests)

- **3 Commits + 2 Tags** auf `chore/clean-architecture`. `persona_base` ist eine **committete,
  getaggte, E2E-bewiesene Einheit**.
- **Working-Tree bewusst klein:** nur die persona_base-Einheit committet. Die übrigen
  (älteren) uncommitteten Phase-Dateien (`controller.py`, `orchestrator.py`, `platform/*`,
  viele Docs, …) sind **intentional nicht** mitgesweeped — sie gehören in separate, eigene Commits.
- **Tests (8 relevante Suites grün):** `test_persona_base`, `test_session_mode_gate`,
  `test_session_mode_task`, `test_session_registry`, `test_pi_provider_session`,
  `test_retry_scrub`, `test_dummy_reject_once`, `test_spec_feedback`.

### Geänderte Dateien (Commit 3)
- `engine/settings.py` — `BASE_SESSION_DIR`, `PERSONA_ID`
- `engine/session_registry.py` — `base_session_dir_for`, pi-konformes `copy_base_to_task`
  (findet Base, kopiert, schreibt interne `id` um), `ROLE_DEPARTMENT`-Map, cap-aware
- `run_pi_mesh.py` — `persona_base`-Gate + Observability-Log
- `tests/test_persona_base.py` (neu, 5 Tests auf echtem pi-Format)
- `docs/Startup.md` — `FIRMA_SESSION_MODE=persona_base` + `FIRMA_PERSONA_ID`
- `docs/Phase6_3_Implementation_Plan.md` — Status auf „E2E BEWIESEN"

---

## 6. Was wir schon können / was noch fehlt

### Schon können (E2E bewiesen)
- Oneshot-deterministische Runs (`off`).
- Task-Mode Retry-Continuity + Disk-Cap (`task`).
- Persona Warm-Base Seeding + Isolation + Cleanup (`persona_base`) — am Counter bewiesen.

### Noch offen / nächste sinnvolle Schritte
1. **(Optional) Latency-Guard für Dev-Runs:** optionales `FIRMA_MODEL_*`-Setzen im Spawn,
   *nur* um 320s-Timeouts bei Free-Modellen zu vermeiden (Qualität bleibt Modell-Sache).
2. **(Empfohlen) Seed-Utility** (`tools/seed_base_session.py` + Doc): reproduzierbares Anlegen
   einer Warm-Base via `pi -p "<seed>" --session-id base --session-dir data/sessions/_base/<dept>/<persona>/<role>/`.
   Macht persona_base im Team nutzbar (aktuell nur Ad-hoc möglich).
3. **(Optional) Snake-E2E mit `persona_base`:** brächte nur Latenz/Quota-Risiko, keine
   zusätzliche Feature-Sicherheit (Kern-Akzeptanz ist bereits bewiesen).
4. **Payload-driven Selektion:** aktuell werden `department`/`persona_id` aus Settings injiziert
   (`PERSONA_ID=default`, Department via `ROLE_DEPARTMENT`-Map). Später aus `payload`/`task-N.md`
   auflösbar — v1 bewusst minimal.
5. **`PROCESS_MODE=resident`** (Live-Prozess, KV-Cache-warm): dokumentiert als **§12 deferred** —
   invasiv (Lifecycle, Windows-PIDs, Crash-Fragilität), Free-Tier cached nicht. Nicht Teil von 6.3.a.
6. **Übrige Phase-Dateien separat committen** (eigene Entscheidung, nicht in diese Session-Achsen-Commits mischen).

---

## 7. Basis-Layout (Referenz)

```
data/sessions/
├── _base/                        # Warm-Bases (immutable, nur copy-source)
│   └── <department>/<persona_id>/<role>/
│        └── <timestamp>_base.jsonl   # pi-Session, interne id="base"
└── <run_id>/                    # Task-Sessions (pro Run, am Ende gelöscht)
    └── <timestamp>_firma_<run>_<task>_<role>.jsonl   # interne id umgeschrieben
```

`ROLE_DEPARTMENT = {PLANNER: planning, CODER: coding, REVIEWER: reviewing}`

---

## 8. P1 — Spawn-Serialisierung (Concurrency-Limiter) E2E bewiesen

- **Commit:** `af8f3976` „P1: Spawn-Serialisierung (Concurrency-Limiter) + Test-Safety-Wachter"
  (Tag `phase6-p1-spawn-serialization-e2e-proven`).
- **Unit-Tests:** `tests/test_p1_spawn_limits.py` — Serialisierung (max concurrent == N) +
  Modell-Pinning-Flags (`--provider/--model` nur bei `FIRMA_MODEL_*`). Alle 9 Tests grün via `tools/safe_test.sh`.
- **E2E-Beweis (Counter, Run `24fb7bbf-ea7a-4b53-a389-5e4348dc82ce`):**
  - Launch: `FIRMA_APP=counter FIRMA_TRANSPORT=pimesh FIRMA_MAX_CONCURRENT_SPAWNS=1 FIRMA_REVIEWER_DUMMY=true SESSION_MODE=off python run_snake.py`
  - **COMPLETED** in ~510s (~8,5 min), echte `pi`-Spawns.
  - Jede Spawn-Zeile `[active_spawns=1/1]` → Semaphor begrenzt Concurrency auf 1, durchgehend.
  - Spawns strikt sequenziell (PLANNER → CODER task-1/2/3 → Retries), nie überlappt.
  - **Keine 429/Rate-Limit-Fehler.** Einzige Härtefälle: HARD TIMEOUT 320s bei task-1/task-2
    (Single-Task Free-Tier-Latenz) → von Retry-Schicht recovered (`successfully recovered from hard timeout`).
  - Fazit: Concurrency-Flakiness-Pfad eliminiert; verbleibende Latenz ist Modell-Thema
    (eigene Infra-Härtung), von Resilienz abgefangen.
- **Test-Safety-Wachter:** `tools/safe_test.{sh,ps1}` — echte Windows-PIDs + rekursiver Tree-Kill,
  Default 150s. Verhindert, dass ein haengender Test (echter `pi` / Free-Tier-Latenz) den Rechner
  ueber Nacht testet. Doku: `docs/Testing_Safety.md` (verbindliche Regel: nie rohes `python`, immer Wachter).
- **Wichtig:** Erster Run ohne `FIRMA_TRANSPORT=pimesh` lief im `WorkerSim`-Modus (kein echter
  Spawn) → beweist P1 NICHT. Korrekter Entrypoint für echte Spawns ist `FIRMA_TRANSPORT=pimesh`.
- **Nächste Schritte:** P2 Seed-Utility, P3 komplexe E2E (Snake+persona_base). `PROCESS_MODE=resident` (§12) deferred.

---

## 9. P2 — Seed-Utility (reproduzierbare persona_base Warm-Bases) E2E bewiesen

- **Commit:** `d4566ef3` (Tag `phase6-p2-seed-utility-e2e-proven`).
- **Tool:** `tools/seed_base_session.py` — seed/verify Base-Sessions ueber den gleichen PiProvider-Pfad
  (`--session-id base --session-dir <BASE_SESSION_DIR>/<dept>/<persona>/<role>`). `--dry-run` zeigt die exakte
  `pi`-Kommandozeile ohne Spawn. `FIRMA_SEED_TIMEOUT` (340s) begrenzt den pi-Spawn.
- **Unit-Test:** `tests/test_seed_utility.py` — Pfad/Struktur/interne id (OHNE pi) + optionaler Integration-Test
  (`FIRMA_RUN_SEED_INTEGRATION=1`).
- **E2E bewiesen:** `python tools/seed_base_session.py --department coding --persona default --role CODER
  --provider kilo --model kilo/kilo-auto/free --id base --seed-prompt-file tools/seeds/coder_base.md`
  → Base `2026-07-18T21-08-15-999Z_base.jsonl` erzeugt (interne id=`base`).
  `--verify --expect BASE_CONTEXT_OK` → `found: True` — Base-Context wird geladen.
- **Nebenfix:** `SessionRegistry._find_base_session_file` retourniert neueste Base (Reseed/Update korrekt).
- **Docs:** `docs/Seeding.md` (How-to seed/verify/rotate) + Pointer in `docs/Startup.md`.
- **Nächste Schritte:** P3 komplexe E2E (Snake + persona_base + echter Reviewer) — jetzt mit reproduzierbarem Seed
  und weniger Flakiness dank P1.

---

## 10. P3 — Komplexe E2E (Snake + persona_base + echter Reviewer) E2E bewiesen

### 10.1 P3.1 — Snake + persona_base + Dummy-Reviewer
- **Run:** `b5c2f538-0d58-41a1-b163-207877fe0bde` — **COMPLETED**, ~3 min, **0 Timeouts**.
- Launch: `FIRMA_TRANSPORT=pimesh FIRMA_APP=snake FIRMA_SESSION_MODE=persona_base FIRMA_PERSONA_ID=default FIRMA_PROCESS_MODE=oneshot FIRMA_REVIEWER_DUMMY=true FIRMA_MAX_CONCURRENT_SPAWNS=1 python run_snake.py`
- persona_base `seeded=True` für CODER task-1/2/3 (Warm-Base aus `data/sessions/_base/coding/default/CODER`).
- Receiver published task-3 genau **einmal**, nach dem echten Write. task-3 → `REVIEW_APPROVED` (Dummy).

### 10.2 P3.2 — Snake + persona_base + ECHTER Reviewer
- **Run:** `c06e14f8-cd51-45a7-8b71-cb440917726d` — **COMPLETED**, ~8 min, **0 Timeouts**.
- Flip: `FIRMA_REVIEWER_DUMMY=false`. Echter Reviewer spawn't pi (REVIEWER-Rolle, **unseeded** → task-mode).
- Alle 3 Tasks `REVIEW_APPROVED` (Receiver erkannte je Task `REVIEW_APPROVED`). persona_base `seeded=True` CODER 1/2/3.
- Fazit: kompletter Multi-Agent-Flow (Planner→Coder→Reviewer) mit persona_base + Serialisierung + echtem Review, E2E grün.

### 10.3 Root-Cause: erster P3.1-Versuch lief FAILED — NICHT wegen Latenz/Prompt
- Erster P3.1 (Run `80d191d5…`) FAILED: task-3 CODER 3× HARD TIMEOUT (320s) → retry budget erschöpft.
- Log-Analyse: Modell HAT `game.js` in ~2 min geschrieben (weit < 320s); Response-Format valide (identisch zu task-1/2, die funktionierten). Also **weder Latenz noch schlechter Prompt**.
- **Ursache:** Stale `worker_response.task-3.response.json` aus einem VORHERIGEN Snake-Run im Crew-cwd (`pimesh/coding-crew/.pi/messenger/crew/`). Launch-Cleanup (`rm worker_response*.response.json`) erfasste nur das Repo-Root, nicht die Crew-Unterverzeichnisse. `PiMeshReceiverLoop` dedup't über `self._consumed` mit Key `(task_id, state_revision)` — **ohne `run_id`**. Die stale Datei (alter run_id) wurde unter `(task-3,1)` als „consumed" markiert; die echte task-3-Antwort dies Runs fiel in denselben Key → **stiller Duplikat-Drop** → task-3 nie erkannt → HARD TIMEOUT.
- **Beweis:** Log `23:38:12 [Receiver] Prepared WorkerResponse for task-3` — das war VOR dem task-3-Spawn (23:39:03). Also wurde eine fremde (stale) Response gepublished.

### 10.4 Fix (dieser Commit)
- `run_pi_mesh.py`: `PiMeshReceiverLoop` wird `run_id`-bewusst:
  - `expected_run_id` im Konstruktor (aus `run_id = await controller.create_run(config)`).
  - `scan_once` extrahiert `run_id` aus Payload; Responses mit fremdem `run_id` werden als stale **übersprungen**.
  - Dedup-Key jetzt `(run_id, task_id, state_revision)`. Konstruktion übergibt `expected_run_id=run_id`.
- Launch-Hygiene: vor jedem Run auch `pimesh/*-crew/.pi/messenger/crew/worker_response*.response.json` + alte Session-Dirs (ausser `_base`) löschen.
- **Regression (empfohlen):** `tests/test_receiver_run_id_dedup.py` (stale fremder run_id → skip; eigener → publish).
- Nach Fix: P3.1b + P3.2 beide **COMPLETED, 0 Timeouts**.

### 10.5 Commit / Tag
- **Commit:** P3 — run_id-aware Receiver-Dedup (stale-file Fix) + Status-Doc.
- **Tag:** `phase6-p3-snake-persona_base-e2e-proven`
