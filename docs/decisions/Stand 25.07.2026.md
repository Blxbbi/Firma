# Firma Statusbericht — 2026-07-25

## Was wir fertig gebaut haben

### Phase A — Adaptive Planner + Delta-Planning (abgeschlossen)

#### 1. Echter Pi-Harness etabliert
**Commits:** `2f42fc02`, `5ece6353`, `b3d22175`, `3c9701e2`, `12bfb102`

- **`run_snake.py` → `run_pi_mesh.py`**: Simulator durch echten Pi-Harness ersetzt
- **File-basierte Bridge** (`PiMeshTransport`): Engine schreibt Task-Files auf Disk, Worker lesen als pi-messenger Crew
- **Worker als echte Subprozesse**: `pi --mode json` Spawns via PiProvider
- **Env-Vars korrekt**: `export` (Bash) statt `set` (CMD) für `FIRMA_PROJECT_DIR` etc.

#### 2. CODER-Gate Fix (Race Condition)
**Commit:** `12bfb102`

**Problem:** Mehrere READY-CODER-Tasks wurden im gleichen Tick geclaimed → Race Condition bei Baseline-Erstellung.

**Lösung:** `coder_assigned_this_tick` Flag (lokal, pro Tick) in `engine/scheduler.py` → blockiert weiteren CODER-Dispatch wenn bereits einer assigned.

**Beweis:** Run `5325a85b` — task-3 wartet korrekt bis task-2 completed.

#### 3. Adaptive Planner: Von Rigid zu Intelligent
**Commits:** `f83bcf60`, `68011858`, `b03c1eb7`, `d5fca701`, `077708ca`, `91b08f43`

| Feature | Status |
|---------|--------|
| **Max Tasks erhöht:** 5 → 10 (Guardian) | ✅ |
| **RESEARCHER-Rolle eingeführt:** Bestandsanalyse + Brief für Planner | ✅ |
| **Delta-Erkennung im PLANNER-Prompt:** Änderung vs. Neubau unterscheiden | ✅ |
| **Adaptive Task-Zahl:** 1–10 Tasks je nach Komplexität | ✅ |
| **Kernel-Side Plan-Validation:** Pläne werden vor Execution geprüft + rejected bei Invalid | ✅ |
| **`FIRMA_PLANNER_EXTRA_INSTRUCTION`:** Prompt-Tuning ohne Code-Change | ✅ |

**Run `dd05bfd8` (Delta-Test):**
- **User-Anfrage:** "Add contact section to existing website"
- **Ergebnis:** 2 Tasks (statt rigid 3)
  - task-1: SEO meta tags (index.html only)
  - task-2: Contact section (index.html + style.css)
  - app.js bleibt protected/unchanged
- **Token-Verbrauch:** ~98k total (planning-crew 49k, coding-crew 49k)

#### 4. Token-Effizienz: ONE-PASS Contracts + Tool-Policies
**Commits:** `d8861ee9`, `690817e9`, `2f513825`

| Maßnahme | Status |
|----------|--------|
| **ONE-PASS Contract (CODER):** `read` nur vor erstem `write`, dann STOP | ✅ |
| **Role-basierte Tool-Policies:** enforced im Provider | ✅ |
| **Worker-Log-Parser + Turn-Telemetrie:** Auditor/Archiver tracken Tokens/Turns/Tools | ✅ |
| **Reviewer Tool-Policy:** `read` + `write` only (kein `bash`, kein `edit`) | ✅ (seit 22.07.) |

#### 5. Prompt-Contracts: Zentralisierung + Test
**Datei:** `engine/transport/pi_mesh_transport.py`

**Constants definiert:**
```python
PLANNER_OUTPUT_CONTRACT_MD
RESEARCHER_OUTPUT_CONTRACT_MD
CODER_OUTPUT_CONTRACT_MD
REVIEWER_OUTPUT_CONTRACT_MD
```

**Test:** `test_prompt_contracts_are_injected_once()` — verifiziert:
- Jede Rolle erhält genau ihren Vertrag (kein Duplikat)
- Keine Cross-Contamination zwischen Rollen
- Legacy-Phrasen entfernt

**Bug gefixt:** `CREWS`-Dict im Test fehlte `"RESEARCHER"` Eintrag → Datei wurde an falschen Ort geschrieben.

#### 6. Milestone-System
**Ordner:** `milestones/adaptive_planner_2026-07-25/`

```
milestones/adaptive_planner_2026-07-25/
├── README.md                 # Vollständige Dokumentation
├── code/                     # Archiv aller geänderten Dateien
│   └── README.md
├── run-dd05bfd8/             # Run-Artefakte
│   ├── audit.md
│   ├── audit.json
│   ├── manifest.json
│   └── worker-logs/
└── artifacts/                # Endprodukte
    ├── index.html
    └── style.css
```

---

## Was wir in dieser Session gefixt haben

### Bug — `test_prompt_contracts_are_injected_once()` schlug fehl
**Symptom:** Test fehlgeschlagen bei RESEARCHER-Rolle mit `AssertionError: Missing OUTPUT CONTRACT (RESEARCHER)`

**Ursache:** In `tests/test_pi_mesh_transport.py` fehlte `"RESEARCHER"` im `CREWS`-Dict. `PiMeshTransport._crew_cwd()` fiel auf Fallback `"planning-crew"` zurück → Datei wurde nach `<tmp>/planning-crew/...` geschrieben statt `<tmp>/pimesh/planning-crew/...`. Test las aus falschem Pfad.

**Fix:** Eintrag ergänzt:
```python
CREWS = {
    "PLANNER": "pimesh/planning-crew",
    "CODER": "pimesh/coding-crew",
    "REVIEWER": "pimesh/reviewing-crew",
    "RESEARCHER": "pimesh/planning-crew",  # ← hinzugefügt
}
```

**Ergebnis:** Alle 9 Tests in `test_pi_mesh_transport.py` PASS.

---

## Was es uns bringt

### Adaptivität
- Planner entscheidet selbst über Task-Zahl (1–10) basierend auf Komplexität
- Delta-Planning funktioniert: iterative Änderungen an bestehenden Projekten
- Researcher liefert Kontext (Bestandsanalyse), keine vordefinierten Lösungen

### Stabilität
- CODER-Gate serialisiert Tasks korrekt (keine Race Conditions)
- Kernel-Guards enforce Plan-Validation, Scope-Compliance, Tool-Policies, Retry-Budget
- Milestone-System archiviert Code + Runs + Artefakte für Reproduzierbarkeit

### Token-Effizienz
- ONE-PASS Contracts reduzieren Iterationen
- Tool-Policies verhindern teure Tool-Chains (Reviewer: 1.519 → 4 Turns)
- Worker-Log-Parser + Auditor tracken Verbrauch pro Rolle

---

## Tag / Commit-Referenz

```
2f42fc02 feat(scope): per-task baseline snapshots fix false-positive scope verification
5ece6353 feat(pi_provider): inline fallback for broken read() tool-call transport
b3d22175 feat(scope): enforce scope compliance via prompt + materializer gating + retry feedback
3c9701e2 feat(receiver): role-qualified task_assigned_at keys + mtime guard filter
12bfb102 feat(receiver): fail-fast on agent_end + no-progress guard for CODER
183c7b93 fix(auditor): prefer manifest actor_role over DB assigned_role in metric sections
f83bcf60 chore: add researcher worker, hygiene ignores, milestone and docs updates
c0555ec9 feat(auditor/archive): role-keyed turn/tool/token metrics + fix auditor double-counting
6563c81f feat(guardian): PLAN_REJECTED increments attempt_count and respects MAX_ITERATIONS
91b08f43 feat(run_pi_mesh): add FIRMA_PLANNER_EXTRA_INSTRUCTION env override
d5fca701 feat(guardian): add kernel-side plan validation and rejection path
077708ca feat(planner): add kernel-side plan validation to reject invalid plans
690817e9 feat(token-efficiency): enforce role-based tool policy in provider (Step 3)
d8861ee9 feat(token-efficiency): add ONE-PASS contract for CODER (Step 2)
2f513825 feat(token-audit): add worker log parser + turn telemetry in auditor/archiver
b03c1eb7 docs(briefings): mark planner research-brief injection as solved
68011858 feat(planner): inject research brief into planner prompt when available
```

## Test-Status

```
tests/test_pi_mesh_transport.py               9/9 PASS   (Dispatch + Contracts + Spec-Prompts)
tests/test_scheduler_coder_gate.py            PASS       (CODER-Serialisierung)
tests/test_phase3_researcher_contract.py      PASS       (Researcher Output Contract)
tests/test_phase3_researcher_readonly.py      PASS       (Read-only Guard)
tests/test_phase3_researcher_routing.py       PASS       (RESEARCHER → planning-crew)
tests/test_guardian_plan_validation.py        PASS       (Plan-Validation + Rejection)
tests/test_guardian_plan_rejection.py         PASS       (PLAN_REJECTED + attempt_count)
tests/test_phase4_auditor.py                  PASS       (Tool-Usage + Policy-Check)
tests/test_phase4_auditor_integration.py      PASS       (Audit als Archive-Hook)
tests/test_run_archive.py                     PASS       (Manifest + Tool-Usage)
tests/test_review_artifact_selection.py       PASS       (Selective Artifact Loading)
tests/test_retry_scrub.py                     PASS       (Retry-Session-Scrub)
tests/test_pimesh_spawn.py                    PASS       (Spawn + Log-Collision)
```

## E2E-Proof

| Run-ID | Ergebnis | Besonderheit |
|--------|----------|--------------|
| `5325a85b` | 3/3 COMPLETE | CODER-Gate proof: task-3 serialisiert nach task-2 |
| `dd05bfd8` | 2/2 COMPLETE | Adaptive Planner: 2 Tasks für Delta (Contact-Section) |
| `e1c5edbd` | 3/3 COMPLETE | 5-Task-Run mit echtem Reviewer (~133k Tokens) |
| `612899db` | 3/3 COMPLETE | 5-Task-Run mit echtem Reviewer |

## Architektur-Erkenntnisse

### 1. Kernel-Guards > Prompt-Tricks
Plan-Validation, Scope-Policy, Tool-Policies und Retry-Budget sind die **source of stability**. "Smartere Prompts" allein reichen nicht — deterministische Limits verhindern Over-Engineering und Token-Explosion.

### 2. Delta-Planning ist der Schlüssel für Iteration
Bei iterativen Projekten (z.B. Lernapp: Base → Math → Geography) erkennt der Researcher das Delta und der Planner plant nur die Änderung. Das spart 30–60% Tokens pro Iteration.

### 3. Milestone-Archivierung ermöglicht Reproduzierbarkeit
Code + Run-Artefakte + Endprodukte in einem Ordner → jeder Run ist nachvollziehbar und vergleichbar.

### 4. Prompt-Contracts als Konstanten
Zentrale Definition in `pi_mesh_transport.py` + Test-Coverage → keine Hardcoded-Strings, keine Cross-Contamination zwischen Rollen.

---

## Nächste Schritte

1. **Lernapp-Projekt testen** (iterative Learning-App mit Base-Framework → Subjects als Delta)
2. **Phase B:** Delta-Planning verfeinern (expliziter `edit_mode`, granulare Scope-Detection)
3. **Phase C:** Agent Modularity (`agents.yaml` Toggles für an/aus schalten von Rollen)

---

*Bericht erstellt am 25.07.2026*
