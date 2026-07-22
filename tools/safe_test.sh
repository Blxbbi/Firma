#!/usr/bin/env bash
# safe_test.sh — Wachter fuer Python-Tests (Firma).
#
# Verhindert, dass ein haengender Test (z.B. echter `pi`-Subprozess auf dem
# langsamen/kostenlosen Modell) den Rechner ueber Nacht testet.
#
# WICHTIG: git-bash $! / kill arbeiten mit SHIM-PIDs, keine echten Windows-PIDs
# -> powershell Stop-Process wuerde ins Leere greifen. Daher delegiert dieses
# Skript an PowerShell, das mit ECHTEN Windows-PIDs arbeitet (Start-Process
# -PassThru + rekursiver Tree-Kill).
#
# Der Python-Pfad wird HIER zu einem echten Windows-Pfad aufgeloest und als
# FIRMA_PY_WIN uebergeben (der Harness setzt PYTHON oft als Unix-Pfad ohne .exe,
# den PowerShell nicht starten kann). Der Test-Output wird via `tee` mitgeschnitten.
#
# Usage: ./tools/safe_test.sh <test.py> [timeout_sec]
set -u
if [ $# -lt 1 ]; then echo "Usage: ./tools/safe_test.sh <test.py> [timeout_sec]"; exit 2; fi
TEST="$(cygpath -w -a "$1")"
TIMEOUT="${2:-150}"
PY="${PYTHON:-/c/Users/arthu/AppData/Local/Python/bin/python3}"
PYWIN="$(cygpath -w "$PY" 2>/dev/null || echo "$PY")"
[[ "$PYWIN" != *.exe ]] && PYWIN="${PYWIN}.exe"
export FIRMA_PY_WIN="$PYWIN"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PS1="$(cygpath -w "$SCRIPT_DIR/safe_test.ps1")"
LOG="/tmp/safe_test_$(basename "$1" .py).log"
powershell -NoProfile -ExecutionPolicy Bypass -File "$PS1" -Test "$TEST" -Timeout "$TIMEOUT" 2>&1 | tee "$LOG"
exit ${PIPESTATUS[0]}
