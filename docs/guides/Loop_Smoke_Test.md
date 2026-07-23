# Loop-Smoke Test (User-Journey über den gesamten Firma-Loop)

- **Datum:** 2026-07-16 (Plan) / **Proven:** 2026-07-20
- **Branch:** `chore/clean-architecture`
- **Status:** ✅ Proven (realer Run + Promote + Verify + surgical edit)
- **Vorgänger:** Phase 1 (Archiv), Phase 2 (Ingest+Scope), Phase 3 (Researcher), Phase 4 (Auditor), Phase 5 (Copy/Promote), F4 (Ingest Project Staging)
- **Zweck:** Einmaliger, realer **End-to-End-Beweis** der gesamten Bedien-Story:
  Ordner → deterministische Guards → Archiv/Audit → menschliches Promote.

> **Warum vor dynamic-base?** Erst die reale User-Journey glatt laufen lassen. UX-Kanten
> (Pfadkonventionen, Wo ist die `run_id`?, Welche Dateien wurden geändert?) zeigen sich
> nur unter echten Bedingungen — bevor neuer „Komfort" gebaut wird.

---

## 0. Beweis (Loop-Smoke Run 5 — 2026-07-20)

**Run-ID:** `8aeff60b-4ada-44e6-840a-a2cdf1d88e0b`
**Transport:** PiMesh (free-tier LLM, `FIRMA_MAX_CONCURRENT_SPAWNS=1`)
**Terminal-State:** `COMPLETED` (Duration 242s, 3 CODER-Timeouts → succeeded on retry 3)

### Assertions erfüllt
- [x] Run endet mit `COMPLETED` (nicht `FAILED`).
- [x] `archive/runs/<run_id>/audit.md` existiert (Phase 4).
- [x] **audit.md → Scope/Drift Summary:** `task task-1: scope=['style.css'], protected=['app.js', 'index.html']`
- [x] **audit.md → Task Table:** RESEARCHER (VERIFIED, research_readonly), PLANNER (VERIFIED), CODER (VERIFIED), REVIEWER (VERIFIED, dummy)
- [x] Promote Exit **0**; `Counter-v2` erstellt mit Provenance.
- [x] `diff -rq Counter-v1 Counter-v2`: nur `style.css` geändert (plus `PROMOTED_FROM_RUN.txt`).
- [x] `diff -u Counter-v1/style.css Counter-v2/style.css`: **chirurgischer Edit** — nur Farbwert `red` → `#00f`, Rest identisch.
- [x] `Counter-Original == Counter-v1` (nie angefasst).

### Chirurgischer Edit (bewiesen)
```diff
--- Projects/Counter/Counter-v1/style.css
+++ workspace/8aeff60b-4ada-44e6-840a-a2cdf1d88e0b/project/style.css
@@ -1 +1 @@
-button { color: red; border: 1px solid #333; }
+button { color: #00f; border: 1px solid #333; }
```

### F4 (Ingest Project Staging) nachgewiesen
- Log: `[PiProvider] staged ingest project for 8aeff60b-.../task-1 -> pimesh/coding-crew/.pi/work/8aeff60b-.../task-1/project`
- CODER las bestehende `style.css` aus dem Staging-Workdir und edierte nur den Farbwert.
- Workspace bleibt Source of Truth für Drift-Messung (Scope-Verifier).

---

## 1. Voraussetzungen

- Firma läuft lokal (free-tier Provider; kein paid model — Flakiness akzeptiert, siehe §6).
- `FIRMA_TRANSPORT=pimesh` (PiMesh, `FIRMA_MAX_CONCURRENT_SPAWNS=1`).
- `FIRMA_PROJECT_DIR` wird auf eine **`-v1`**-Arbeitskopie gesetzt (nie auf `-Original`).
- `run_snake.py` als Entrypoint (korrekt, wired `messenger_callback` + `PiProvider`).
- `tools/promote_run.py` vorhanden (Phase 5.1).

---

## 2. Projekt-Fixture (einmalig angelegt)

```
Projects/
  Counter/
    Counter-Original/        # frozen source of truth (wird NIE als FIRMA_PROJECT_DIR gesetzt)
    Counter-v1/              # Arbeitskopie = Kopie von -Original (hier wird der Run gestartet)
```

`Counter-Original/` (und damit `Counter-v1/`) enthält ein minimales statisches Web-Projekt:

**index.html**
```html
<!DOCTYPE html>
<html><head><link rel="stylesheet" href="style.css"></head>
<body><button id="b">Klick mich</button><script src="app.js"></script></body></html>
```

**style.css** (Ausgang: rot)
```css
button { color: red; border: 1px solid #333; }
```

**app.js**
```js
document.getElementById('b').addEventListener('click', () => console.log('clicked'));
```

Anlegen:
```bash
mkdir -p Projects/Counter/Counter-Original Projects/Counter/Counter-v1
# obige 3 Dateien nach Counter-Original/ schreiben
cp -r Projects/Counter/Counter-Original/. Projects/Counter/Counter-v1/
```


---

## 3. Der Run (Schritt-für-Schritt)

```bash
# 1) Umgebung
export FIRMA_TRANSPORT=pimesh
export FIRMA_APP=counter
export FIRMA_PROJECT_DIR="$(pwd)/Projects/Counter/Counter-v1"
export FIRMA_REVIEWER_DUMMY=true
export FIRMA_MAX_CONCURRENT_SPAWNS=1
export FIRMA_SESSION_MODE=off
export FIRMA_PROMPT="Change ONLY the button color in style.css to #00f (blue). Do NOT modify any other file (no index.html, no app.js). Write only the updated style.css."

# 2) Launch + warten (200-300s bei free-tier)
python run_snake.py > /tmp/loop_smoke.log 2>&1

# 3) run_id merken (oder: ls -t archive/runs | head -1)
```

**Prompt-Regel (wichtig):** explizit auf EINE Datei beschränken — das ist der Scope,
den der Scope-Verifier (Phase 2) durchsetzt.

---

## 4. Assertions (der Loop-Beweis)

### 4.1 Run + Archiv + Auditor
- [ ] Run endet mit `COMPLETED` (nicht `FAILED`).
- [ ] `archive/runs/<run_id>/audit.md` existiert (Phase 4).
- [ ] **audit.md → Scope/Drift Summary:** einzige Änderung ist `style.css`
      (scope=['style.css'], protected=['app.js', 'index.html']).
- [ ] **audit.md → Task Table:** RESEARCHER/PLANNER/CODER/REVIEWER alle `COMPLETE`.

### 4.2 Promote (Phase 5)
```bash
python tools/promote_run.py \
  --run_id <run_id> \
  --target_dir "$(pwd)/Projects/Counter/Counter-v2"
```
- [ ] Exit-Code **0**.
- [ ] `Projects/Counter/Counter-v2/` enthält die Projekt-Kopie.
- [ ] `Projects/Counter/Counter-v2/PROMOTED_FROM_RUN.txt` existiert, enthält `<run_id>` + Link auf `audit.md`.

### 4.3 Verify: nur style.css geändert, Original unberührt
```bash
# Diff v1 vs v2: ausschließlich style.css darf sich unterscheiden
diff -rq Projects/Counter/Counter-v1 Projects/Counter/Counter-v2
# erwartet: nur style.css unterscheidet sich

# Original muss identisch zu sich selbst bleiben (kein Firma-Zugriff)
diff -rq Projects/Counter/Counter-Original Projects/Counter/Counter-v1
# erwartet: KEINE Unterschiede (v1 wurde nur gelesen, nicht überschrieben)
```
- [ ] `Counter-v1` vs `Counter-v2`: einziger Unterschied ist `style.css` (`#00f`).
- [ ] `Counter-Original` vs `Counter-v1`: identisch (Original unangetastet).

---

## 5. Happy Path (erwartet)

```
Counter-Original/style.css : color: red        (frozen)
Counter-v1/style.css       : color: red        (input, unverändert nach Run)
Counter-v2/style.css       : color: #00f       (promoted output)
```
Researcher schreibt read-only Brief, CODER ändert nur `style.css` (Scope erzwungen),
Auditor dokumentiert Drift, Mensch promoted via Tool → `Counter-v2`.

---

## 6. Bekannte Hürden (free-tier LLM)

> **Hinweis:** Loop-Smoke ist **manuell** (echte LLMs, nicht deterministisch).
> Er beweist die UX, nicht die Engine-Korrektheit (die ist durch die Phasen-E2Es abgesichert).

- **Flakiness:** Der free-tier Provider kann den Scope verfehlen oder timeouten.
  Bei `FAILED` mit `SCOPE_VIOLATION`/`PROTECTED_VIOLATION`: Run wiederholen, nicht manuell fixen.
- **Mehrfach-Versuche:** Ein Run kann iterieren (Retry). Das ist erwartbar; der Auditor zeigt
  Attempts/Guards.
- **F4 Staging:** Falls der CODER die staged Dateien unter `.pi/work/<run_id>/<task_id>/project/`
  nicht findet, prüfe ob `FIRMA_TRANSPORT=pimesh` gesetzt ist (Staging ist PiMesh-only).

---

## 7. Wenn der Smoke glatt läuft → nächster Schritt

Erst nach einem sauberen Loop-Smoke entscheiden, ob **dynamic-base-as-folder** (Vision-Doc)
wirklich nötig ist — oder ob das Ordnerkonventionsmodell (`-Original`/`-vN`) schon ausreicht.

---

*Dies ist eine abgeschlossene Checkliste. Ausführung: 2026-07-20, Run `8aeff60b-4ada-44e6-840a-a2cdf1d88e0b`.*
