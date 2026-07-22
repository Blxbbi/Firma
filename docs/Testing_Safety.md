# Testing Safety — immer einen harten Timeout (Wachter)

**Status:** aktiv / verbindlich. **Stand:** 2026-07-18.

## Warum das existiert

Ein einzelner Test kann den Rechner **über Nacht am Testen hindern**, wenn er
unbegrenzt hängt. Reale Auslöser im Firma-Projekt:

- Ein **echter `pi`-Subprozess** in einem Test, der auf das langsame/kostenlose
  Modell wartet (Free-Tier-Congestion, 320s-Hard-Timeout) oder auf `stdin`
  blockt.
- Ein **Deadlock im Test-Harness** (Race beim Freigeben von Ressourcen), der
  `asyncio.run` nie zurückkehren lässt.

Ein solcher Hang hat **kein eingebautes Timeout** — er läuft, bis der Prozess
von außen gekillt wird. Daher gilt: **es gibt IMMER einen logischen Timeout.**

## Die goldene Regel

> **NIEMALS** `python tests/X.py` ohne Wachter starten.
> **IMMER** `./tools/safe_test.sh tests/X.py [timeout_sec]` nutzen.

Der Wachter (`tools/safe_test.sh` → `tools/safe_test.ps1`) garantiert:

1. **Hartes Timeout** (Default `150s`, pro Aufruf überschreibbar).
2. Bei Überschreitung wird der **gesamte Prozess-Baum** (python + `pi`/`node`
   Kinder) über **echte Windows-PIDs** rekursiv getötet.
3. Korrekte Exit-Codes: `0` = PASS, `≠0` = FAIL, `124` = TIMEOUT.

## Vorab gewonnene Lektionen (sonst funktioniert der Wachter nicht)

- **Git-Bash `$!` / `kill` sind SHIM-PIDs**, keine echten Windows-PIDs.
  `powershell Stop-Process -Id <ShimPID>` greift ins Leere → Wachter ist
  wirkungslos. Daher läuft der Wachter als **PowerShell-Skript**, das die echte
  PID via `Start-Process -PassThru` holt.
- **`Start-Process -RedirectStandardOutput/-Error` liefert in dieser
  PowerShell-Version KEINEN `ExitCode`** (bleibt leer). Daher kein Redirect im
  Wachter; der Test-Output wird vom Bash-Shim via `tee` mitgeschnitten.
- Der Python-Pfad wird im Bash-Shim zu einem **echten Windows-Pfad** (`.exe`)
  aufgelöst und als `FIRMA_PY_WIN` übergeben — der Harness setzt `PYTHON`
  oft als Unix-Pfad ohne `.exe`, den PowerShell nicht starten kann.

## Usage

```bash
# Standard (150s Hard-Timeout)
./tools/safe_test.sh tests/test_p1_spawn_limits.py

# Enger Timeout für verdächtige Tests (z.B. 60s)
./tools/safe_test.sh tests/test_p1_spawn_limits.py 60
```

Ausgabe (Beispiel):

```
[safe_test] RUN C:\...\tests\test_p1_spawn_limits.py  timeout=60s  py=...
[safe_test] exit=0 PASS
```

Bei Hang:

```
[safe_test] TIMEOUT 15s -> Prozessbaum toeten (pid=25752)
[safe_test] exit=TIMEOUT
```

## Unit-Tests dürfen KEINEN echten `pi` spawnen

Ein Unit-Test, der `PiProvider().spawn_for_assignment(...)` gegen den echten
`pi`-Binärstartet, ist ein **Hang-Risiko** und gehört nicht in die
Regression-Suite. Regeln:

- Nutze `StubProvider` / `FakeProc` / `FakeTransport` (siehe
  `tests/test_p1_spawn_limits.py`).
- Echte Modell-Flags (`--provider/--model`) werden über
  `subprocess.Popen`-Monkeypatching getestet, nicht über echten Spawn.
- Worker-Procs im Stub sind **selbst-freigebend** (Timer), damit ein Race beim
  Freigeben den Test nie deadlockt.

## Echte E2E-Runs (Snake/Counter mit echtem `pi`)

Für echte End-to-End-Runs (die bewusst `pi` starten) gilt:

```bash
# Im Hintergrund mit Hart-Timeout + Log
nohup timeout 1800 python run_snake.py ... > archive/logs/e2e.log 2>&1 &
# Echten Win-PID sichern (NICHT git-bash ps!)
tasklist | grep -i python
# Sauberes Beenden (Agent=node 14708 / Swarm=node 5508 NIEMALS toeten)
powershell -NoProfile -Command "Stop-Process -Id <WIN_PID> -Force"
```

## Checkliste vor jedem Test-Lauf

- [ ] Läuft der Test über `./tools/safe_test.sh` (nicht rohes `python`)?
- [ ] Ist der Timeout gesetzt (Default 150s reicht für Unit-Tests)?
- [ ] Spawnt der Test einen echten `pi`? → Wenn ja: stubben oder als E2E kennzeichnen.
- [ ] Nach Lauf: `tasklist | grep -iE "python|node"` → keine verwaisten Prozesse
      außer Agent (14708) / Swarm (5508).
```
