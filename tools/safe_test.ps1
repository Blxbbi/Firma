param(
  [Parameter(Mandatory=$true)] [string]$Test,
  [int]$Timeout = 150
)
# Wachter mit ECHTEN Windows-PIDs (git-bash $! ist nur ein Shim -> Stop-Process no-op).
# Python-Pfad kommt als $env:FIRMA_PY_WIN (vom Bash-Shim in Windows-Form aufgeloest).
#
# WICHTIG: Start-Process -RedirectStandardOutput/-Error liefert in dieser
# PowerShell-Version KEIN ExitCode (bleibt leer). Daher KEIN Redirect -> der
# Test-Output wird vom Bash-Shim via `tee` in eine Log-Datei gespichert.
# $p.Id ist die echte python-PID -> Kill-Tree toetet python + dessen Kinder (pi/node).
$py = if ($env:FIRMA_PY_WIN) { $env:FIRMA_PY_WIN } else { 'C:\Users\arthu\AppData\Local\Python\bin\python3.exe' }
Write-Host "[safe_test] RUN $Test  timeout=${Timeout}s  py=$py"

function Kill-Tree($rootId) {
    Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $rootId } | ForEach-Object { Kill-Tree $_.ProcessId }
    try { Stop-Process -Id $rootId -Force -ErrorAction SilentlyContinue } catch {}
}

$p = Start-Process -FilePath $py -ArgumentList $Test -PassThru -ErrorAction Stop
if (-not $p) { Write-Host "[safe_test] FEHLER: Prozess nicht gestartet (py=$py)"; exit 2 }

$ok = $p.WaitForExit($Timeout * 1000)
if (-not $ok) {
    Write-Host "[safe_test] TIMEOUT ${Timeout}s -> Prozessbaum toeten (pid=$($p.Id))"
    Kill-Tree $p.Id
    Write-Host "[safe_test] exit=TIMEOUT"
    exit 124
}
$p.Refresh()
$code = $p.ExitCode
Write-Host "[safe_test] exit=$code $(if($code -eq 0){'PASS'}else{'FAIL'})"
exit $code
