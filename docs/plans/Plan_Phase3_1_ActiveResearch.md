# Plan Phase 3.1 — Active Researcher (Projekt-Explorer + optional Web)

- **Datum:** 2026-07-20
- **Branch:** `chore/clean-architecture`
- **Status:** Draft / not implemented
- **Vorgänger:** Phase 3 (Researcher, Idee B) — read-only Briefing
- **Ziel:** Der Researcher wird vom reinen „Prompt-zusammenfassen" zum **aktiven Informationssammler**:
  1. Liest bestehende Projektdateien (Projekt-Explorer)
  2. Recherchiert optional im Web (Docs, Bibs, Funfacts)
  3. Übergibt einen strukturierten Brief an Planner/Coder
  4. Bleibt read-only, implementiert nichts, keine Rekursion

---

## 0. Warum jetzt?

- **Phase 2 Vision:** „Iterativ editieren statt rewrite" — **erfüllt** (F4-Staging, chirurgische Edits)
- **Phase 3 Status:** Researcher schreibt einen Brief — **aber ohne Projektkontext** (kein Lesezugriff auf Bestandsdateien)
- **Problem:** Planner muss aus dem Prompt allein raten, wo im Code etwas geändert werden muss → unvollständige Plans → from-scratch Rewrites
- **Lösung:** Researcher liest die relevanten Dateien, sammelt Kontext, gibt strukturierten Brief an Planner

---

## 1. Aktueller Stand (vor Phase 3.1)

### Was funktioniert
- Researcher wird automatisch vor Planner dispatched (via `dependencies=[researcher_task.id]`)
- Researcher schreibt `research/brief.md` (read-only, Guardian prüft)
- Planner bekommt `research_brief` in Task-Definition

### Was fehlt
- Researcher hat **keinen Lesezugriff** auf Projektdateien (kein Staging)
- Researcher macht **keine Web-Recherche** (keine Tools, kein Web-Zugriff)
- Brief ist **frei formatiert** (keine Struktur, keine Citations)

---

## 2. Phase 3.1 — Schritt R1: Projekt-Explorer Researcher (low risk)

### Was neu kommt
- **F4-Staging für RESEARCHER:** `workspace/<run_id>/project/` wird in `<crew_cwd>/.pi/work/<run_id>/<task_id>/project/` kopiert (wie für CODER)
- **Researcher-Prompt erweitert:** „Lies die relevanten Dateien im staged project tree, nenne konkrete Stellen (Datei+Zeile oder Suchstring), und schreibe brief.md."
- **Strukturierter Brief:** `research/brief.md` enthält Abschnitte:
  - `Project findings (with citations)` — was im Code steht, mit Referenzen
  - `Recommendations for planner` — konkrete Vorschläge, wo anfassen
  - `Risks/constraints` — was zu beachten ist
- **Citation Guards:** Jede Behauptung über den Code muss eine Referenz enthalten:
  - `file: path`, `evidence: exact snippet` oder `search term`

### Was sich nicht ändert
- Researcher bleibt **read-only** (Guardian prüft Baseline-Diff + Artefakt-Policy)
- Researcher schreibt **nur** `research/brief.md` (kein Code, keine `plan_draft`)
- Keine Rekursion (nur ein Researcher-Task am Anfang)

### Risiko
- **Niedrig:** Rein lokal, keine externen Abhängigkeiten, deterministisch testbar
- **Guardrails:** Guardian prüft, dass Researcher nur `research/` schreibt + Projektdateien unverändert bleiben

---

## 3. Phase 3.1 — Schritt R2: Web Research optional (controlled, nicht default)

### Was neu kommt
- **Opt-in via Env:** `FIRMA_RESEARCH_WEB=0|1` (default `0`)
- **Wenn aktiviert:** Researcher darf Web-Query machen (wenn Tools verfügbar)
- **Pflichtangaben im Brief:**
  - Quellen als Links/IDs
  - Kurze, extrahierte Fakten (keine langen Copy-Pastes)
  - Klare Markierung: `external info` vs `project code evidence`

### Was sich nicht ändert
- Researcher bleibt **read-only** (kein Code, keine Projektdateien ändern)
- Keine Rekursion (nur ein Researcher-Task am Anfang)
- Web-Recherche ist **nicht deterministisch** → nur für Runs aktivieren, wo es Sinn macht

### Risiko
- **Mittel:** Web-Zugriff hängt von Provider/Tools ab (nicht immer verfügbar)
- **Mitigation:** Default `0`, explizites Opt-in, Quellenangabe-Pflicht, Budget-Limit (max N Queries)

---

## 4. Architektur-Entscheidungen

### Ein Researcher oder mehrere?
**Ein Researcher-Agent (Option A), aber mit strukturierter Brief-Vorlage.**

Warum?
- Einfacher zu testen, zu debuggen, zu warten
- Prompt kann intern trennen: `Project findings` vs `External info`
- Später (wenn A unzuverlässig wird) auf mehrere spezialisierte Agenten aufsplitten

### Wo liegt der „Source of Truth" für den Researcher?
- **F4-Staging:** `<crew_cwd>/.pi/work/<run_id>/<task_id>/project/` (read-only Referenz)
- Researcher liest daraus, schreibt nur `research/brief.md`
- Guardian prüft, dass `project/` unverändert bleibt (Baseline-Diff)

### Handoff an Planner
- Kein P2P, keine magische Zustandsübergabe
- Einfache Datei: `workspace/<run_id>/research/brief.md`
- Planner bekommt Pfad als `research_brief` in Task-Definition

---

## 5. Implementation Plan

### Schritt R1 (Projekt-Explorer) — 1 Woche
1. **`pi_provider.py`:** F4-Staging auf `role in ("CODER", "RESEARCHER")` erweitern
2. **`pi_mesh_transport.py`:** Researcher-Prompt erweitern (Projekt-Exploration + Citation Guards)
3. **Unit-Tests:**
   - `test_piprovider_ingest_stage.py` erweitern: RESEARCHER wird gestaged
   - Neuer Test: `test_researcher_citation_guard.py` — Brief ohne Citation wird abgelehnt
4. **Light-Integration:**
   - Stub-Researcher liest Dateien aus staged project, schreibt Brief mit Citations
   - Assert: Brief enthält `file:`-Referenzen + `evidence:`
5. **E2E:**
   - Interner Transport + Stub-Researcher + Stub-Planner + Stub-Coder
   - Assert: Run COMPLETED, Brief enthält Projekt-Referenzen, Planner nutzt Brief für Plan

### Schritt R2 (Web Research) — 1 Woche (nach R1)
1. **`engine/settings.py`:** `FIRMA_RESEARCH_WEB` hinzufügen (default `0`)
2. **`pi_mesh_transport.py`:** Researcher-Prompt um Web-Recherche-Abschnitt erweitern (wenn Env gesetzt)
3. **Unit-Tests:**
   - `test_researcher_web_mode.py` — Web-Modus aktiviert/deaktiviert
   - `test_researcher_web_citation.py` — Quellenangabe-Pflicht im Brief
4. **Light-Integration:**
   - Stub-Researcher mit Web-Search (simuliert)
   - Assert: Brief enthält `external info`-Abschnitt mit Links
5. **E2E:**
   - Wie R1, aber mit aktiviertem Web-Modus
   - Assert: Brief enthält Web-Quellen + Projekt-Referenzen

---

## 6. Tests (Deterministik-Prinzip)

### Unit
- `test_piprovider_ingest_stage.py` — RESEARCHER staging (erweitern)
- `test_researcher_citation_guard.py` — Brief ohne Citation wird abgelehnt
- `test_researcher_web_mode.py` — Web-Modus aktiviert/deaktiviert
- `test_researcher_web_citation.py` — Quellenangabe-Pflicht

### Light Integration
- InternalTransport + Stub-Researcher (liest Projektdateien, schreibt Brief mit Citations)
- Assert: Brief enthält `file:`-Referenzen + `evidence:`

### E2E
- Interner Transport + Stub-Researcher + Stub-Planner + Stub-Coder
- Assert: Run COMPLETED, Brief enthält Projekt-Referenzen, Planner nutzt Brief für Plan

---

## 7. Risikos und Mitigation

| Risiko | Wahrscheinlichkeit | Impact | Mitigation |
|---|---|---|---|
| Researcher liest Projektdateien (read-only) | ✅ Kein Risiko | Keiner | Guardian prüft Baseline-Diff |
| Researcher macht Web-Recherche | ✅ Kein Risiko (nur extern) | Keiner | Opt-in via Env, Quellenangabe-Pflicht |
| Researcher schreibt Code | ❌ Risiko | Hoch | Guardian: Artefakt-Policy + Baseline-Diff → FAILED |
| Rekursion (Researcher → Planner → CODER → Researcher) | ❌ Risiko | Mittel | Researcher wird nur EINMAL dispatched (keine Dependency-Schleife) |
| Web-Recherche failt/ratelimittet | ⚠️ Mittel | Mittel | Default `0`, Opt-in, Budget-Limit |
| Halluzination (falsche Code-Referenzen) | ⚠️ Mittel | Mittel | Citation Guards: jede Behauptung braucht `file:` + `evidence:` |

---

## 8. Akzeptanzkriterien

### R1 (Projekt-Explorer)
- [ ] Researcher wird gestaged (F4 für RESEARCHER aktiv)
- [ ] Brief enthält `file:`-Referenzen + `evidence:` (Citations)
- [ ] Run COMPLETED mit strukturiertem Brief
- [ ] Planner nutzt Brief für Plan (keine from-scratch Rewrites)
- [ ] Alle Regressionstests grün (Phase 1–5 + Phase 3)

### R2 (Web Research)
- [ ] `FIRMA_RESEARCH_WEB=0` (default) → kein Web-Zugriff
- [ ] `FIRMA_RESEARCH_WEB=1` → Web-Recherche aktiv
- [ ] Brief enthält `external info`-Abschnitt mit Quellen (Links/IDs)
- [ ] Kurze Fakten (keine langen Copy-Pastes)
- [ ] Alle Regressionstests grün

---

## 9. Timeline

| Woche | Schritt | Status |
|---|---|---|
| 1 | R1: Projekt-Explorer Researcher | Geplant |
| 2 | R2: Web Research optional | Geplant (nach R1) |
| 3 | Tests + Regression + Tag | Geplant |

---

## 10. Nächste Schritte

1. **Plan review** — ist das so gewollt?
2. **R1 implementieren** — F4-Staging für RESEARCHER + Prompt + Citations
3. **Tests bauen** — Unit + Light Integration + E2E
4. **R2 implementieren** — Web-Modus optional
5. **Commit + Tag** — `phase3.1-active-researcher-proven`

---

*Dies ist ein Plan/Draft. Implementation erfolgt nach Freigabe.*
