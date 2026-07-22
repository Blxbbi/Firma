# Firma Statusbericht — 2026-07-20

## Was wir fertig gebaut haben

### Phase 1–5 (bereits vor dieser Session)
- **Phase 1**: Run-Archivierung (Archiver + Provenance)
- **Phase 2**: Ordner-Ingest + Scope-Guards (chirurgisches Editieren statt Rewrite)
- **Phase 3**: Researcher (read-only Briefing, Drift-Schutz)
- **Phase 4**: Auditor (deterministisches Audit, LLM-frei)
- **Phase 5**: Copy/Promote (Tool + Runbook, Original bleibt unberührt)

### F4 — Ingest Project Staging (diese Session)
**Commit `64a2b594` + Tag `loop-smoke-f4-proven`**

**Problem**: Der CODER-Worker bekam keine bestehenden Projektdateien zu sehen → musste alles from-scratch schreiben → kein chirurgisches Edit möglich.

**Lösung**: `PiProvider` kopiert `workspace/<run_id>/project/` vor dem Spawn in `<crew_cwd>/.pi/work/<run_id>/<task_id>/project/` (mit Exclusions für `.pi/`, `.git/`, `node_modules/`). Worker erhält Prompt mit klarer Anweisung: *„lies aus `.pi/work/.../project/`, editiere chirurgisch, schreibe Ergebnis nach `.pi/messenger/crew/`"*.

---

## Was wir in dieser Session gefixt haben

### Bug 1 — RESEARCHER nicht in PiMesh geroutet
**Symptom**: Run 1 (`de190be9`) → 3× WORKER_TIMEOUT (320s)
**Ursache**: `RESEARCHER` fehlte in `PIMESH_CREWS`, `ROLE_TO_CREW`, `ROLE_TARGET_EVENT`, `PIMESH_MODELS`
**Fix**: Registrierung + `RESEARCH_COMPLETE`-Ziel + read-only Brief-Prompt
**Commit**: `8eddfd72`

### Bug 2 — `research/brief.md` landete im Projekt-Tree
**Symptom**: Run 2 (`9f9de380`) → false Drift-Alarm (`research\brief.md` als Projekt-Drift)
**Ursache**: `materialize_to_workspace` hardcodete `project/` als Basis → Brief landete INNERHALB des Projekt-Trees
**Fix**: `research/`-Artefakte gehen ins Schwester-`research/`-Verzeichnis
**Commit**: `8eddfd72`

### Bug 3 — `plan_draft` nur in Side-File, Receiver liest sie nicht
**Symptom**: Run 3 (`126cef4e`) → COMPLETED mit nur 2 Tasks (RESEARCHER+PLANNER), kein CODER-Task
**Ursache**: Planner schrieb Plan in `plan_draft.<task>.json` (Side-File), Receiver holte nur aus Response-JSON → Guardian bekam `plan_draft=None` → keine CODER-Tasks
**Fix**: Receiver liest Side-File deterministisch als Fallback (Race-sicherer Defer)
**Commit**: `a405b72a`

### Bug 4 — CODER hatte keinen Lesezugriff auf Projektdateien
**Symptom**: Run 4 (`40ad6cbc`) → CODER schrieb `style.css` from-scratch (Default-Snake-CSS), kein chirurgischer Edit
**Ursache**: `PiProvider.spawn_for_assignment` kopierte `workspace/<run_id>/project/` nicht ins Crew-CWD
**Fix**: F4-Staging in task-spezifisches Workdir + Prompt-Erweiterung
**Commit**: `64a2b594`

---

## Was es uns bringt

### Der Loop funktioniert end-to-end (bewiesen)
```
Ordner (Counter-v1) 
  → Ingest + Scope-Guards 
  → Researcher (read-only Brief) 
  → Planner (Plan mit CODER-Tasks) 
  → CODER (chirurgisches Edit) 
  → Reviewer 
  → Archiv + Audit 
  → Promote → Counter-v2
```

### Konkrete Beweise (Run `8aeff60b-4ada-44e6-840a-a2cdf1d88e0b`)
- ✅ Terminal-State: `COMPLETED`
- ✅ `style.css`: nur `color: red` → `color: #00f` (chirurgisch)
- ✅ `index.html`, `app.js`: unberührt (Protected)
- ✅ `Counter-Original == Counter-v1` (nie angefasst)
- ✅ Promote Exit 0, Provenance geschrieben
- ✅ Audit existiert, Scope/Drift korrekt dokumentiert

### Was die Phase 2-Vision endlich einlöst
**Vorher**: „Iterativ editieren" war ein from-scratch Rewrite (weil der CODER die Bestandsdateien nicht lesen konnte).

**Jetzt**: Echter chirurgischer Edit — der Worker sieht die bestehende Datei, ändert nur die eine Zeile, die Scope-Guards prüfen exakt diese Änderung. Das ist der Kernnutzen von Phase 2.

---

## Was wir jetzt damit machen können

### Sofort
1. **Echte Projekte incrementell bearbeiten** — `FIRMA_PROJECT_DIR=Projects/MeinProjekt/v1` → Run → `v2` mit nur den gewünschten Änderungen
2. **Loop-Smoke als Blaupause** — das Counter-Beispiel ist die Vorlage für beliebige Projekte
3. **Researcher + Auditor produktiv nutzen** — Read-only Briefing + Audit-Report für jeden Run

### Kurz bis mittelfristig
4. **Dynamic-Base-as-Folder entscheiden** — Vision-Doc-Idee: ob `-Original`/`-vN`-Konvention ausreicht oder ein `dynamic-base`-Feature nötig ist
5. **Deterministischer Ingest-Edit-Planner** (optional) — falls der free-tier Planner mal wieder keinen CODER-Task erzeugt (Bug 3 ist gefixt, aber LLM-Compliance ist nie garantiert)
6. **Mehr Worker-Rollen** — z.B. TESTER, DEVOPS; das Staging-Muster (F4) kann auf REVIEWER erweitert werden

### Architektur-Erkenntnisse
- **Free-tier LLMs sind kein Bottleneck** — alle 4 Bugs waren Plumbing-Probleme, keine LLM-Qualitätsprobleme
- **Deterministische Guards funktionieren** — Scope, Protected-Files, Read-only-Forschung, Audit laufen ohne LLM
- **PiMesh ist produktiv tauglich** — mit den Fixes läuft der volle Loop über echte Worker

---

## Tag / Commit-Referenz

```
64a2b594 feat(F4): stage ingest project into crew workdir for surgical CODER edits
a405b72a fix(loop-smoke): recover planner plan_draft from side-file
8eddfd72 fix(loop-smoke): wire RESEARCHER into pimesh + route research/ artifacts

Tag: loop-smoke-f4-proven (Run 8aeff60b-4ada-44e6-840a-a2cdf1d88e0b)
```
