"""Phase 6.1: SessionRegistry unit tests (deterministic, no network)."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import engine.settings as settings
from engine.session_registry import SessionRegistry as sr


def test_session_id_stable_and_scoped():
    a = sr.session_id_for("run-1", "task-1", "CODER")
    assert a == "firma_run-1_task-1_CODER"
    # idempotent
    assert sr.session_id_for("run-1", "task-1", "CODER") == a
    # andere Task/Role -> andere id
    assert sr.session_id_for("run-1", "task-2", "CODER") != a
    assert sr.session_id_for("run-1", "task-1", "REVIEWER") != a


def test_session_dir_is_run_scoped():
    assert sr.session_dir_for("run-X") == Path(settings.SESSION_DIR) / "run-X"


def test_is_collaborative_reflects_env():
    orig = sr.FIRMA_MODE
    try:
        sr.FIRMA_MODE = "collaborative"
        assert sr.is_collaborative() is True
        sr.FIRMA_MODE = "deterministic"
        assert sr.is_collaborative() is False
    finally:
        sr.FIRMA_MODE = orig


def test_cleanup_run_removes_dir():
    orig = sr.SESSION_DIR
    with tempfile.TemporaryDirectory() as tmp:
        try:
            sr.SESSION_DIR = tmp
            d = sr.session_dir_for("run-Z")
            d.mkdir(parents=True, exist_ok=True)
            (d / "x.txt").write_text("hi")
            assert d.exists()
            sr.cleanup_run("run-Z")
            assert not d.exists()
        finally:
            sr.SESSION_DIR = orig


if __name__ == "__main__":
    test_session_id_stable_and_scoped()
    test_session_dir_is_run_scoped()
    test_is_collaborative_reflects_env()
    test_cleanup_run_removes_dir()
    print("ALL TESTS PASSED")
