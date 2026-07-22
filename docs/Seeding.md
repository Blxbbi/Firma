# Seeding — reproduzierbare persona_base Warm-Bases

**Gehoert zu:** Phase 6.3, Schritt P2. **Stand:** 2026-07-18.

`persona_base` (6.3.a) kopiert beim Task-Spawn eine **Base-Session** als Warm-Context.
Damit das im Team-Alltag nutzbar ist, braucht es einen **standardisierten, reproduzierbaren**
Weg, Base-Sessions zu erzeugen, zu verifizieren und zu rotieren. Das ist `tools/seed_base_session.py`.

## Wozu
- Base-Sessions sind der Cold-Start-Grounding-Context der Worker (Style/Projektkonventionen).
- Ohne Seed-Utility war Seeding Ad-hoc (pi von Hand) → nicht reproduzierbar, schwer zu pruefen.
- P3 (Snake + persona_base + echter Reviewer) ist nur aussagekraeftig, wenn der Seed reproduzierbar ist.

## Base-Pfad
`BASE_SESSION_DIR/<department>/<persona_id>/<role>`  (z.B. `data/sessions/_base/coding/default/CODER`).
`BASE_SESSION_DIR = SESSION_DIR/_base`. Die interne Session-id der Base ist immer `base`
(pi matched Sessions ueber die **interne id**, nicht den Dateinamen).

## Seed erzeugen
```bash
python tools/seed_base_session.py \
  --department coding --persona default --role CODER \
  --provider kilo --model kilo/kilo-auto/free \
  --id base --seed-prompt-file tools/seeds/coder_base.md
```
- Nutzt den **gleichen** `PiProvider`-Spawnpfad wie Firma (oneshot, `--mode json -p`),
  aber mit `--session-id base` und `--session-dir <base_dir>`.
- Schreibt `<timestamp>_base.jsonl` nach `<base_dir>` (interne id = `base`).
- Ende-Ausgabe: `base_dir`, `session_file`, `internal_id`, `result: SUCCESS/FAIL`.

## Verifizieren (dass die Base geladen wird)
```bash
python tools/seed_base_session.py --verify \
  --department coding --persona default --role CODER \
  --provider kilo --model kilo/kilo-auto/free \
  --id base --expect BASE_CONTEXT_OK
```
- Spawnt erneut mit gleicher session id/dir, fragt den Marker ab.
- `found: True` + `result: SUCCESS` ⇔ Base-Context ist im Worker angekommen.

## Rotieren
Base ist **immutable** (nur Copy-Quelle). Neu-Seeden = alte Base ersetzen:
```bash
# komplett neu
rm -rf data/sessions/_base/coding/default/CODER
python tools/seed_base_session.py --department coding --persona default --role CODER \
  --provider kilo --model kilo/kilo-auto/free --id base --seed-prompt-file tools/seeds/coder_base.md
```

## Dry-Run (Mechanik pruefen, KEIN pi-Spawn)
```bash
python tools/seed_base_session.py --department coding --persona default --role CODER \
  --provider kilo --model kilo/kilo-auto/free --id base \
  --seed-prompt-file tools/seeds/coder_base.md --dry-run
```
Druckt die exakte `pi`-Kommandozeile, spawned aber nicht.

## Hinweise
- `--provider/--model` optional: wenn unset, nutzt `pi` seinen Default.
- `FIRMA_SEED_TIMEOUT` (Default 340s) begrenzt den einzelnen pi-Spawn, damit das Script nicht haengt.
- Die Base wird nur verbraucht, wenn ein Run mit `FIRMA_TRANSPORT=pimesh` UND
  `FIRMA_SESSION_MODE=persona_base` gestartet wird (siehe `docs/Startup.md`).
- Seed-Text (`tools/seeds/coder_base.md`) ist bewusst minimal: nur **Grounding/Style**,
  keine Task-Vorgaben (vermeidet Konflikt mit Task-Specs).
