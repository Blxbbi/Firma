"""Phase 6.1: MANATEE smoke test (Session-Kontinuitaet ueber Retries).

Opt-in via FIRMA_CONTINUITY_SMOKE=1. Erfordert die `pi`-CLI plus Netz/Key.
Bei fehlendem Flag oder fehlender CLI wird der Test uebersprungen (Advisor-ratified).

Beweis (Session-ID Strategie): ein frischer `pi -p --session-id <id> --session-dir <dir>`
laden den Kontext aus der Session-Datei des VORHERIGEN `pi`-Aufrufs (gleiche ID).
"""
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_PI = shutil.which("pi")
_ENABLED = os.environ.get("FIRMA_CONTINUITY_SMOKE") == "1" and _PI is not None


def _pi_spawn(session_id, session_dir, prompt, timeout=180):
    proc = subprocess.run(
        [_PI, "--mode", "text", "--session-id", session_id,
         "--session-dir", session_dir, "-p", prompt],
        capture_output=True, text=True, timeout=timeout,
    )
    return proc.stdout + proc.stderr


def test_session_continuity_mantlee():
    sid = "firma_test_continuity_coder"
    with tempfile.TemporaryDirectory() as tmp:
        sdir = os.path.join(tmp, "sess")
        out1 = _pi_spawn(sid, sdir, "Remember the secret token: MANATEE-77. Reply with the token only.")
        assert "MANATEE-77" in out1, f"token missing in first response: {out1[-500:]}"
        out2 = _pi_spawn(sid, sdir, "What was the secret token I told you earlier? Reply with it only.")
        assert "MANATEE-77" in out2, f"token not recalled: {out2[-500:]}"


if __name__ == "__main__":
    if not _ENABLED:
        print("SKIP: MANATEE smoke not enabled (set FIRMA_CONTINUITY_SMOKE=1 and ensure `pi` CLI).")
        raise SystemExit(0)
    test_session_continuity_mantlee()
    print("ALL TESTS PASSED")
