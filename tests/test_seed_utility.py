"""P2 — Tests fuer das Seed-Utility (tools/seed_base_session.py).

test_seed_utility_writes_base_dir_structure:  Unit, OHNE pi.
  - Pfadberechnung (mit/ohne session_dir-Override)
  - Verzeichnis-Erzeugung
  - _find_base_session_file + interne id (pi-konform: Match ueber interne id)

test_seed_utility_integration_optional:  ECHTER pi-Spawn, daher OPTIONAL.
  - nur bei FIRMA_RUN_SEED_INTEGRATION=1 (sonst SKIP). Langsam/quota-abhaengig.
Lauf: python tests/test_seed_utility.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.seed_base_session import compute_base_dir, ensure_base_dir, _read_internal_id
from engine.session_registry import SessionRegistry
from engine.settings import BASE_SESSION_DIR


def test_seed_utility_writes_base_dir_structure():
    # 1) Pfadberechnung ohne Override == kanonischer Settings-Pfad
    d = compute_base_dir("coding", "default", "CODER")
    assert d == SessionRegistry.base_session_dir_for("coding", "default", "CODER")
    assert d == BASE_SESSION_DIR / "coding" / "default" / "CODER"

    # 2) session_dir-Override wird direkt genutzt (Isolation/Tests)
    assert compute_base_dir("coding", "default", "CODER", session_dir="/tmp/x") == Path("/tmp/x")

    # 3) Verzeichnis-Erzeugung
    tmp = Path(tempfile.mkdtemp())
    target = tmp / "coding" / "default" / "CODER"
    ensure_base_dir(target)
    assert target.is_dir()

    # 4) synthetische Base-Session-Datei wird gefunden + interne id korrekt
    sf = target / "2026-07-18T00-00-00-000Z_base.jsonl"
    sf.write_text(json.dumps({"type": "session", "version": 3, "id": "base"}) + "\n")
    found = SessionRegistry._find_base_session_file(target)
    assert found == sf
    assert _read_internal_id(sf) == "base"

    # 5) Falsche interne id wird nicht als Base verwechselt (Suffix-Prio)
    other = target / "2026-07-18T00-00-00-000Z_other.jsonl"
    other.write_text(json.dumps({"type": "session", "id": "other"}) + "\n")
    assert SessionRegistry._find_base_session_file(target) == sf


def test_seed_utility_integration_optional():
    if not os.environ.get("FIRMA_RUN_SEED_INTEGRATION"):
        print("SKIP test_seed_utility_integration_optional (set FIRMA_RUN_SEED_INTEGRATION=1)")
        return
    import subprocess
    repo = Path(__file__).parent.parent
    script = repo / "tools" / "seed_base_session.py"
    seed = repo / "tools" / "seeds" / "coder_base.md"
    tmp = Path(tempfile.mkdtemp())
    base = ["python", str(script), "--department", "coding", "--persona", "default",
            "--role", "CODER", "--id", "base", "--provider", "kilo",
            "--model", "kilo/kilo-auto/free", "--session-dir", str(tmp)]
    r1 = subprocess.run([*base, "--seed-prompt-file", str(seed)], timeout=400)
    assert r1.returncode == 0, "seed failed"
    r2 = subprocess.run([*base, "--verify", "--expect", "BASE_CONTEXT_OK"], timeout=400)
    assert r2.returncode == 0, "verify failed"


if __name__ == "__main__":
    test_seed_utility_writes_base_dir_structure()
    test_seed_utility_integration_optional()
    print("ALL TESTS PASSED")
