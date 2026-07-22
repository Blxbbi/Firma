# Vision & Design — Inkrementelle Entwicklung, Researcher, Auditor, Run-Archiv

**Status:** Draft / not implemented
**Datum:** 2026-07-19
**Branch:** `chore/clean-architecture`
**Kontext:** Aufbauend auf Phase 5 / 6 / P1 / P2 / P3 (bewiesene, deterministische, Free-Tier-E2E).
**Ziel dieses Docs:** Vollständige, begründete Erfassung aller besprochenen Erweiterungs-Ideen —
inkl. Vision, heutigem Problemzustand, Lösungsansatz, Hürden und *Sinn und Grund* pro Idee.

---

## 0. Ausgangslage — womit wir es zu tun haben

Firma ist eine **deterministische KI-Execution-Engine**. Bewiesen (committet + getaggt):

- **Phase 5/6.1/6.2:** Narrative Logs, Session-ID-Strategie, Feedback-Loop + Retry-Scrub + Escalation.
- **6.3 Schritt 1/2 + persona_base (6.3.a):** `SESSION_MODE` × `PROCESS_MODE` entkoppelt; Warm-Base copy-on-start.
- **P1 Spawn-Serialisierung:** kein 429/Rate-Limit mehr (Semaphor). Tag `phase6-p1-spawn-serialization-e2e-proven`.
- **P2 Seed-Utility:** reproduzierbare persona_base Warm-Bases + Verify. Tag `phase6-p2-seed-utility-e2e-proven`.
- **P3 komplexe E2E (Snake + persona_base + echter Reviewer):** beide Runs COMPLETED, 0 Timeouts.
  Dabei einen **Stale-File-Bug** im `PiMeshReceiverLoop` gefunden/gefixt (Dedup-Key ohne `run_id`)
  + Regression-Test gebaut. Tag `phase6-p3-snake-persona_base-e2e-proven`.

**Leitprinzipien, die wir nicht verletzen wollen:**
1. **Infrastruktur vor Modell** — Context/Prompt härten, bevor ein Modell gewechselt wird.
2. **Nur Free-Tier-Modelle** — keine paid models.
3. **Best-effort Determinismus** — *gleiche Inputs → gleicher FSM-Verlauf + gleiche Artefakt-Constraints*.
   Konkret gefordert: `temperature=0` (bzw. deterministische Sampling-Parameter, soweit pi/Provider das
   hergeben), festes Toolset + Reihenfolge, identische Base-Sessions (falls `persona_base` aktiv),
   gleiche Dateisystem-Reihenfolge (Windows-Reihenfolge-Unterschiede vermeiden).
   **Ehrlich:** der LLM-Output selbst kann variieren — aber **Verifier/Review sind deterministisch**,
   und der Artefakt-Contract (scope/protected) ist hart. Das ist stark genug und ehrlich.
4. **7 Invarianten** — v. a. (1) Kernel-State-Sovereignty, (7) Security Boundary, Push-only Kontext.
5. **PiProvider = Compute-Substrat, nicht Orchestrator**; **PiMesh = Bridge, nicht Hard-Replace**.

**Warum dieses Doc:** Wir stehen an der Schwelle vom *One-Shot-Builder* zum *iterativen Dev-Partner*.
Die folgenden Ideen sind keine isolierten Features, sondern ein kohärentes nächstes Evolutions-Bündel.

---

## 1. Leitbild (das große Bild)

> **Firma = „Wende diese Anweisung auf diesen bestehenden Codebase-Ordner an."**
> Universal, deterministisch, mit Mensch-in-der-Schleife als letzter Autorität.

- **Eingabe:** ein existierender Projekt-Ordner (den Firma nie gebaut haben muss) + ein User-Prompt.
- **Ablauf:** Researcher erkundet → Planner plant das Delta → Coder setzt um → Verify + Review.
- **Sicherheit:** Original bleibt unangetastet; gearbeitet wird auf einer Kopie; das Original wird
  **nur manuell** (vom Menschen) überschrieben, wenn alles 100 % sicher ist.
- **Gedächtnis:** Runs werden archiviert; der Projekt-Ordner ist die persistente Wahrheit (versioniert).

---

## 2. Idee A — Inkrementelle / iterative Entwicklung (bestehendes Projekt weiterbearbeiten)

### 2.1 Vision
User: *„Hey, die Snake soll einen blauen Schweif bekommen, Rest bleibt."*
Firma bekommt den bestehenden `Snake/`-Ordner + diesen Prompt, schaut rein, versteht, und
implementiert **nur den Delta** — den Rest lässt sie unangetastet.

### 2.2 Problem heute (warum es so noch nicht geht)
- **Runs sind `run_id`-isoliert** (bewusste Invariante: „All entities in a run share the same run_id
  to prevent cross-talk"). Jeder Run startet frisch aus dem App-Config.
- **Task-Sessions sind nach Run-Ende weg** (Design: `data/sessions/<run_id>/` wird gereinigt).
- **`persona_base` ist statisch** (einmal per Seed-Tool erzeugt), nicht vom Vor-Run-Ergebnis abgeleitet.
- **Coder-Spec ist „create from zero"** (Snake-Config: „Create exactly these three files").
- **Kein State-Handoff:** ein neuer Run hat keinen „Rest", den er erhalten könnte.

### 2.3 Lösungsansatz (Ordner-Ingest + Delta)
1. Ein Run kann **von einem existierenden Ordner starten** (der als Kopie in das Working-Dir gelegt wird).
2. **Researcher** erkundet diesen Ordner (read-only) → liefert Verständnis.
3. **Planner** erzeugt eine **Delta-Spec** („ändere game.js: blauer Schweif"; index.html/style.css bleiben).
4. **Coder** **editiert** die bestehenden Dateien (statt neu zu erschaffen).
5. **Verify + Review** prüfen das Ergebnis.
6. **Iteration = selber Ordner + neuer Prompt.** Keine Snapshot-Maschinerie nötig.

### 2.4 Hürden / offene Punkte
- **Spec-Contract muss edit-orientiert + explizit sein (H1).** Heute ist die Snake-Spec „create".
  Das ist ein Config-/Contract-Wechsel. Konkret geplantes Schema (siehe H1):
  - `task_definition.scope_files = [...]` — welche Dateien der Coder anfassen darf.
  - `task_definition.protected_files = [...]` (oder „alles andere geschützt") — harte Regel:
    „Ändere NUR die in scope gelisteten Files."
- **„Rest bleibt" ist eine Verifier-Mechanik, kein nur-Prompt-Problem (H2):**
  - Beim Ordner-Ingest erzeugt der Kernel ein **Baseline-Manifest** (Hash pro File) (oder nutzt
    ArtifactStore CAS-Revisions).
  - Nach CODING prüft der Verifier: nur erlaubte Files geändert · unveränderte Files gleicher Hash ·
    keine neuen Dateien außerhalb Allowlist. → deterministischer Guard gegen
    „LLM hat index.html umformatiert".
- **Coder-Working-Dir muss mit den existierenden Dateien befüllt werden** (die Kopie), nicht leer starten.
- **Best-effort Determinismus bleibt gewahrt** (siehe §0.3).

### 2.5 Sinn und Grund
- **Warum:** Echte Software-Arbeit ist iterativ, nicht One-Shot. „Add level 34 / blauer Schweif" ist
  die Realität; ein nur-gen-from-scratch-Builder deckt den Alltag nicht ab.
- **Warum Ordner statt Firma-Snapshot:** universal (jeder Ordner funktioniert), keine
  pro-Projekt-Zustandspflege im Engine-Kern, deutlich simpler. Der Ordner IST die Wahrheit.

---

## 3. Idee B — Researcher-Agent (Exploration, kein Code-Schreiben)

### 3.1 Vision
Ein **read-only Explorer**: findet relevanten Kontext (welche Bibliotheken der Coder nutzen sollte,
wichtige Infos aus Web/Lokal), bereitet **Briefings** für Planner/Coder auf. Schreibt **keinen
Projekt-Code**, sondern nur Informations-Artefakte.

### 3.2 Platzierung
- **Planning-Abteilung** (füttert Planner + CODER vorab). `ROLE_DEPARTMENT` um `RESEARCHER → planning` ergänzen.
- Theoretisch auch Coding denkbar; Planning ist der natürliche Ort für vorgelagerte Kontext-Sammlung.

### 3.3 Kein P2P — Artefakt-Handoff (bewusste Entscheidung)
- **Problem bei P2P:** Agent-zu-Agent-Kommunikation, die am Kernel vorbei geht, verletzt
  **Invariante 1 (Kernel-State-Sovereignty)** und **Push-only**.
- **Lösung:** Researcher schreibt einen **„Research-Brief" als Artefakt** (Datei/Doc); Planner/Coder
  konsumieren ihn über den bestehenden `ArtifactStore`. Faktisch derselbe Handoff, aber im Kernel-Bus.
- **Sinn:** gleicher Nutzen wie P2P, ohne neue Autorität/neues Kommunikations-Substrat; sicherer.

### 3.4 Seeding — bewusst NICHT biasen
- **Keine Persona-Seed für Researcher.** Eine feste „So forschst du grundsätzlich"-Base würde die
  Stärke (unvoreingenommenes Recherchieren) kaputt machen → gewollter Bias.
- **Projekt-Kontext** kommt aus dem **Ordner + Researcher-Exploration** (Fakten, kein Bias).
  Ist anfrage-unabhängig (Snake bleibt Snake) → biast nicht pro Anfrage.
- **Knowledge/Content-Pack** (z. B. „PyCharm-Doku", Domain-Korpus) ist eine *Inhalts*-Seed, keine
  Verhaltens-Seed → sinnvoll, **optional, pro Domain**.
- **`persona_base` (P2) bleibt als optionales Rollen-Stil-Polish** erhalten, aber **entkoppelt von
  Projekten** (kein pro-Projekt-Seed nötig).

### 3.5 Hürden
- Researcher muss die Projekt-Dateien **sehen können** → setzt Idee A (Ordner-Ingest) voraus.
- **Kosten:** extra LLM-Calls; gemindert durch billiges/schnelles Modell + weniger Coder-Rework.
- **Muss strikt read-only bleiben** (Security Boundary — darf Original nicht mutieren).

### 3.6 Sinn und Grund
- **Warum:** Coder wird in die richtigen Bibliotheken/Infos „gegroundet" → weniger Rate-Limit-/Retry-
  Risiko durch falsche Ansätze, bessere Outputs.
- **Warum kein Seed:** Universalität. Wir wollen nicht für jedes Projekt eine Seed pflegen; der Prompt
  + Ordner reichen, der Researcher erkundet selbst.

---

## 4. Idee C — Auditor-Agent (Abschlussbericht / Post-Run-Report)

### 4.1 Vision
Ein Agent, der **am Ende eines Runs** einen Bericht schreibt: wie viele Tokens welcher Agent verbraucht
hat, wer wie lange woran gearbeitet hat, was schiefging, wie viele Retries, wann/wo/was.

### 4.2 Platzierung
- **Letzte Task im Run** (Rolle `AUDITOR`), nachdem alles `COMPLETE` ist. Bleibt im Run-Scoping
  (keine neue Autorität).
- Komplementär zur Live-View: Auditor = *post-hoc*, Dashboard = *echtzeit*.

### 4.3 Datenquelle
- **Bereits vorhanden:** Narrative-Logs, Run-DB-Events (Retry-Zähler, Timeouts, Eskalationen),
  Artifact-Metadaten, pro pi-Turn `usage` (input/output/cacheRead).
- **Lücke:** aggregierte **Token-/Zeit-Werte pro Agent** liegen evtl. noch nicht *strukturiert* in der
  Kernel-DB (stecken in Worker-Logs). → braucht **leichte Metrics-Erfassung** (pro Task/Agent Tokens +
  Dauer als Event).

### 4.4 Hürden
- **Metrics-Capture-Erweiterung** nötig (klein, aber real).
- Muss **read-only Consumer** bleiben (nur lesen, nicht in den Run eingreifen).

### 4.5 Sinn und Grund
- **Warum:** Observability/Audit; exakt die „was wann schief, welcher Ablauf"-Frage (verknüpft mit
  Run-Archiv, Idee D). Billig, weil Daten größtenteils schon da sind.

---

## 5. Idee D — Run-Archivierung

### 5.1 Vision
Runs **behalten** (nicht löschen): Backtrack, Timeline, „was wurde falsch gemacht, was ist wann
passiert, wie ist der Ablauf".

### 5.2 Was bereits da
- `ArtifactStore` persistiert Artefakte (DB + Files).
- Narrative-Logs + Run-DB-Events existieren pro Run.

### 5.3 Hürden
- **Cleanup vs. Archiv:** aktuelles Launch-Cleanup entfernt Run-Session-Dirs (außer `_base`). Für
  Archivierung muss ein **expliziter Archiv-Bereich** erhalten bleiben (z. B. `archive/runs/<run_id>/`).
- **Storage-Wachstum:** ggf. Retention-Policy (alte Runs komprimieren/löschen nach N).

### 5.4 Sinn und Grund
- **Warum:** Lernen, Auditor-Input, Regression-Analyse, Nachvollziehbarkeit. Sehr hoher Wert bei
  minimalem Aufwand (Plumbing größtenteils vorhanden).

---

## 6. Idee E — Copy-Modell & manuelles Promoten (Safety)

### 6.1 Vision
- **Original immer liegen lassen.** Arbeit nur auf einer **Kopie**.
- Original wird **nur manuell** (Mensch) überschrieben, wenn alles 100 % sicher ist — **nicht automatisch**.

### 6.2 Warum (Sinn und Grund)
- **Security Boundary (Invariante 7):** Agenten mutieren niemals die Source-of-Truth.
- **Menschliche Letzt-Entscheidung:** Promoten ist ein bewusster, reviewbarer Schritt.
- **Einfaches Review:** Diff Kopie vs. Original.

### 6.3 Hürden
- Klarer **Promote-Schritt** nötig (Mensch kopiert verifizierte Kopie über Original).
- Versionierte Kopien (`v1..vN`) als Konvention (siehe Idee F).

---

## 7. Idee F — „Dynamische Project-Base" als Ordner-Konvention (nicht als Engine-Feature)

### 7.1 Die Idee (vom User eingebracht)
Unter `Projects/` ein Ordner pro Projekt, z. B. `Snake/` mit `Snake-Original` und dann
`Snake-v1, v2, v3, v4…` (immer aktualisiert).

### 7.2 Empfehlung: Konvention ja, Engine-Feature nein
- **Konvention (jetzt, gratis):** Du legst Ordner an, behältst `Snake-Original`, versionierst Kopien.
  Reine Filesystem-Disziplin, **null Engine-Arbeit**, gibt History + Safety + Backtrack.
- **Engine auto-Snapshot (deferred):** Dass Firma nach jedem Run automatisch eine Base snapshot-tet,
  ist **nicht nötig** — das Ordner-Modell (Idee A/E) deckt es ab. Schwerer Mechanismus entfällt.

### 7.3 Sinn und Grund
- **Warum:** History/Backtrack/Promote-Loop ohne Engine-Komplexität.
- **Warum nicht als Feature:** Universalität & Einfachheit; wir wollen keinen pro-Projekt-Zustand
  im Kern.

---

## 8. Gesamtbild — wie die Teile zusammenspielen

```
Projects/Snake/
├── Snake-Original/        # unangetastete Wahrheit (Idee E/F)
├── Snake-v1/              # versionierte Kopie nach Run 1 (Idee E/F)
├── Snake-v2/              # versionierte Kopie nach Run 2 (iterativ, Idee A)
└── ...

Run (Idee A):  Ordner=Snake-v1 (Kopie) + Prompt="blauer Schweif"
  ├─ Researcher erkundet Ordner (Idee B, read-only)
  ├─ Planner plant Delta-Spec (edit, nicht create)  (Idee A.4)
  ├─ Coder editiert Kopie  (Idee A.3)
  ├─ Verify+Review (Rest bleibt?)  (Idee A.4)
  ├─ Auditor schreibt Abschlussbericht (Idee C)
  └─ Run wird archiviert (Idee D)
Mensch: prüft Kopie, promotet manuell zu Snake-v2 (Idee E)
```

**Invarianten bleiben gewahrt:** Kernel sovereign (Idee B Artefakt-Handoff), Security Boundary
(Original nie auto-mutiert, Idee E), Push-only, Determinismus (Ordner+Prompt+Modell→Ergebnis).

---

## 9. Sammelübersicht — offene Hürden / Risiken

| # | Hürde | Betrifft | Art | Sinn/Grund der Adressierung |
|---|---|---|---|---|
| H1 | Spec-Contract edit-orientiert + Schema `scope_files`/`protected_files` | A, Coder | Mechanik | Delta nur mit explizitem Scope; Coder darf nur scope-Files ändern |
| H2 | Verifier-Baseline-Manifest (Hash pro File) prüft „Rest bleibt" | A | Mechanik | deterministic guard gegen unbeabsichtigte Änderungen/Regression |
| H3 | Coder-Working-Dir aus existierendem Ordner befüllen | A | Mechanik | Delta-Edit setzt bestehende Dateien voraus |
| H4 | Aggregierte Per-Agent-Metrics erfassen | C | Daten | Auditor braucht strukturierte Token/Zeit-Werte |
| H5 | Run-Cleanup vs. Archiv-Retention | D | Infra | Archiv darf nicht vom Cleanup vernichtet werden |
| H6 | Researcher strikt read-only erzwingen | B | Sicherheit | Security Boundary (kein Original-Mutate) |
| H7 | Free-Tier-Latenz bei mehr Agenten/Last | alle | Residuum | Resilienz (Retry/Eskalation) bleibt die Auffanglinie |
| H8 | Promotes sind rein manuell (UX) | E | Mensch | letzte Autorität beim Menschen belassen |

---

## 10. Nächste Schritte — Phasenplan (reordered, risk-first)

Empfehlung (Review bestätigt): kleinste Risiken zuerst; **Archiv VOR Auditor** (sonst ist der
Auditor-Bericht schwer nachvollziehbar).

1. **Run-Archivierung (Idee D)** — *sofort*. Erhöht Debug-/Lernfähigkeit für alles Folgende.
   H5 (Cleanup-vs-Retention) klären; Retention `keep-last-N` + Kompression (siehe §11 Q6).
2. **Ordner-Ingest + Coder-Edit (Idee A + H3 + Teile H1/H2)** — erster echter Produktwert.
   `scope_files`/`protected_files` (H1) + Baseline-Manifest-Verifier (H2) direkt mitbauen.
3. **Researcher (Idee B)** — sobald Ingest existiert (sonst hat er nichts zu sehen). H6 (read-only).
4. **Auditor (Idee C)** — wenn Archiv + strukturierte Metrics (H4) da sind.
5. **Copy/Promote-Konvention (E/F)** — parallel als Doku/Runbook, wenig Code.

**Disziplin:** pro Phase wie gewohnt — erst Unit, dann E2E, dann commit+tag. Kein Code bisher
verändert; dies ist der rein dokumentierte Entwurf.

## 11. Offene Fragen & Empfehlungen (Diskussionsstand)

Die folgenden 6 Fragen wurden im Review gestellt; die Antworten sind **Empfehlungen (⌖)**,
vom Freigebenden zu bestätigen.

**Q1 — Einheit der Ordner-Ingest-Kopie?**
⌖ **Gesamter Projektbaum** (rekursiv), den der User angibt. Universal + simpel; Subfolder-Auswahl
wäre Extra-Config. Edge: sehr große Bäume → Retention/Perf, nicht Korrektheit.

**Q2 — Working-Dir pro Run + Mapping ArtifactStore?**
⌖ `workspace/<run_id>/project/` als Working-Copy. Coder arbeitet dort. Archiv: Kopie von
`workspace/<run_id>/` → `archive/runs/<run_id>/`. ArtifactStore protokolliert Metadaten (CAS);
die Working-Copy ist das live-Artefakt.

**Q3 — Planner: edit vs create — explizit oder automatisch?**
⌖ **Automatisch, wenn Zieldateien in der Working-Copy existieren** (Anwesenheit = Signal), mit
optionalem App-Config-Override (z. B. Snake „from scratch" beim Erst-Build). Universal, kein
pro-Projekt-Config.

**Q4 — read-only für Researcher: wie strikt technisch?**
⌖ **Defense-in-Depth:** (a) Prompt-Regel, (b) Researcher schreibt nur nach
`workspace/<run_id>/research/` (eigenes writable Subdir), Projekt-Dateien liegen in `…/project/`
(für Researcher nur lesbar via Pfad, kein Write-Target), (c) Baseline-Manifest-Verifier (H2)
bestätigt: project-Files unverändert. OS-Perms optional als Hart-Härtung (Windows-fiddly).

**Q5 — Artefaktform des Researchers?**
⌖ **Strukturiertes Markdown** `workspace/<run_id>/research/brief.md` (mensch+LLM lesbar) + optional
`brief.json` (maschinenlesbare Findings: empfohlene Libs, Referenzen, Risiken). Brief = Artefakt,
via Store von Planner/Coder konsumiert.

**Q6 — Archiv-Retention?**
⌖ **keep-last-N + Kompression** (nicht unbegrenzt). Default z. B. N=20 Runs/Projekt; darüber
Working-Copies komprimieren (`.tar.gz`). Immer erhalten: Baseline-Manifest + Run-Log + Auditor-Report
(klein, langfristige Trends).

---

*Dokument erfasst den Diskussionsstand vom 18./19.07.2026. Alle Punkte sind Entwurf; Implementierung
erfolgt erst nach Freigabe, bewiesen durch E2E, dann committet+getaggt (bewährter Disziplin).*
