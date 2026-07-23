# Copy / Promote Runbook (Phase 5, Idee E/F)

**Zweck:** Firma bearbeitet immer nur eine **Kopie** (`workspace/<run_id>/project`). Dieses Runbook
legt fest, wie ein Mensch Projekte versioniert, einen Run reviewed und das Ergebnis **manuell**
„befördert" (promoted) — ohne dass Firma jemals das Original oder den Run-State verändert.

> **Konvention, kein Feature:** Firma erzwingt keine dieser Regeln im Code. Die Autorität über
> Versionierung liegt beim Menschen. Das `tools/promote_run.py`-Script ist nur ein sicherer Copy-Helper.

---

## 1. Verzeichnis-Konvention

```
Projects/
  <name>/
    <name>-Original/     # Source-of-Truth, FROZEN. Wird NIE als FIRMA_PROJECT_DIR gesetzt.
    <name>-v1/           # 1. Arbeitskopie (Initial = Kopie von -Original)
    <name>-v2/           # durch Promote entstanden
    <name>-v3/           # ...
```

- Das **`-Original`** ist die unantastbare Referenz/Baseline. Es wird nie von Firma gelesen/geschrieben.
- Jeder Run arbeitet auf einer **`-vN`**-Kopie (via `FIRMA_PROJECT_DIR`).
- Firma kopiert `<name>-vN` nach `workspace/<run_id>/project` (Ingest) und schreibt nur dort hinein.

---

## 2. Run starten (auf einer `-vN`-Kopie)

```bash
# Initial: Arbeitskopie aus dem Original anlegen
cp -r Projects/<name>/<name>-Original Projects/<name>/<name>-v1

# Run auf v1
export FIRMA_PROJECT_DIR="$(pwd)/Projects/<name>/<name>-v1"
python run_snake.py --prompt "Ändere den Button von rot auf blau (nur style.css)"
```

- Firma ingestet `<name>-v1` → `workspace/<run_id>/project`.
- Researcher → Planner → Coder → Verifier/Guardian laufen; Scope-Verifier begrenzt die CODER-Änderung.
- Am Ende: Run-Archiv + `audit.md`.

---

## 3. Review (vor dem Promote)

Öffne `archive/runs/<run_id>/audit.md` und prüfe:

1. **Run Overview** — `terminal_state` == `COMPLETED`?
2. **Task Table** — alle Tasks `COMPLETE`? Keine `FAILED`?
3. **Scope / Drift Summary** — welche Files geändert? Entspricht das dem erwarteten Edit?
   (Bei Ingest läuft der Scope-Verifier; unerwartete Änderungen erscheinen hier.)
4. **Research Summary** — falls ein Researcher lief: Brief gelesen?
5. **Failures & Retries** — bei `FAILED`: welcher Guard hat ausgelöst? Grund akzeptabel?
6. **Artifacts / Deliverables** — Lieferumfang plausibel?

> **Regel:** Nur promoten, wenn `audit.md` sauber ist. Bei Drift/Scope-Verstoß: Run wiederholen,
> nicht den Workspace manuell „reparieren".

---

## 4. Manuelles Promote (3 Optionen)

### Option A — `tools/promote_run.py` (empfohlen, sicher)
```bash
python tools/promote_run.py \
  --run_id <run_id> \
  --target_dir "$(pwd)/Projects/<name>/<name>-v2"
```
- Kopiert `workspace/<run_id>/project` → `<name>-v2` (nur neu, **kein Overwrite**).
- Schreibt `PROMOTED_FROM_RUN.txt` (run_id, Zeitstempel, Link auf `audit.md`, Firma-Commit).
- **Sicherheitschecks:** target darf nicht existieren (Refusal), keine Pfad-Traversal.
- Exit-Codes: `0` ok · `2` refused (Guard) · `3` source fehlt.

### Option B — `cp` / `rsync` (manuell)
```bash
cp -r workspace/<run_id>/project Projects/<name>/<name>-v2
```
- Mensch ist selbst für „target existiert nicht" verantwortlich.

### Option C — Git
```bash
cp -r workspace/<run_id>/project Projects/<name>/<name>-v2
cd Projects/<name>/<name>-v2 && git init && git add -A && git commit -m "promote from <run_id>"
```

Danach: nächster Run nutzt `<name>-v2` als `FIRMA_PROJECT_DIR`.

---

## 5. „Never touch Original" — Regeln

- `-Original` wird **nie** als `FIRMA_PROJECT_DIR` gesetzt.
- Firma schreibt ohnehin nur in `workspace/<run_id>/project` (Ingest-Kopie), nie nach `Projects/...`.
- Promote schreibt **nur in ein neues, leeres Ziel** (`-vN+1`), nie in-place, nie zurück ins Original.
- Das Promote-Tool lehnt ein existierendes Ziel ab (auch wenn es leer ist) → kein Überschreiben.

---

## 6. Typische Fehler

| Fehler | Symptom | Fix |
|---|---|---|
| Run auf `-Original` gestartet | Original verändert | Nie tun. Immer auf `-vN` arbeiten. |
| Promote-Ziel existiert schon | Tool weigert sich (Exit 2) | Anderen Versionsnamen wählen (`-v3`, nicht `-v2`). |
| Drift im Scope | `audit.md` zeigt unerwartete File-Änderungen | Run wiederholen, nicht manuell fixen. |
| `audit.md` zeigt `FAILED` | Guard ausgelöst | Ursache im Audit lesen; ggf. Prompt/Ingest anpassen. |

---

## 7. Rollback / Backtrack

- Alte `-vN`-Verzeichnisse werden **nie gelöscht**. Ein Rollback = einfach die vorherige `-vN` wieder
  als `FIRMA_PROJECT_DIR` nutzen.
- Das `-Original` bleibt immer als tiefste Baseline erhalten.
- `workspace/<run_id>/project` ist ohnehin flüchtig (pro Run); bei Bedarf neu aus `-vN` ingesten.

---

## 8. Sicherheitsmodell (warum das Original sicher ist)

1. **Ingest = Kopie:** Firma liest `<name>-vN` und schreibt nur in `workspace/<run_id>/project`.
2. **Kernel schreibt nicht nach `Projects/`:** kein Code-Pfad promoted automatisch.
3. **Tool ist defensiv:** target-must-not-exist + Traversal-Abwehr + nur-neu-Kopie.
4. **Menschliche Autorität:** Promote ist ein bewusster, einzelner Befehl — kein Hook, kein Auto.

*Teil von Phase 5 (Idee E/F). Runbook (5.0); das Promote-Script ist `tools/promote_run.py` (5.1).*
