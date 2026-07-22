"""Phase 6.3.a persona_base — Warm-Base copy-on-start: Unit + Wiring-Tests.

Beweist (pi-konform: Sessions sind <ts>_<id>.jsonl mit interner id im ersten JSONL):
- copy-on-start atomar + vollstaendig (Base-Datei kopiert, interne id auf target umgeschrieben).
- Base bleibt immutable (Task-Mutation aendert Base nicht).
- Kein Cross-Task Bleed (Task2 sieht Task1-Geheimnis nicht).
- Cap-Ueberschreitung -> Fail-safe (kein Crash, kein Seed).
- Gate seeded bei SESSION_MODE=persona_base die Task-Session aus der Base.

Lauf: python tests/test_persona_base.py
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.session_registry import SessionRegistry
import run_pi_mesh


class FakeTransport:
    async def dispatch(self, payload, review_artifacts=None):
        self.dispatched = payload

    async def publish_response(self, role=None, payload=None, correlation_id=None):
        self.published = payload


class FakeProvider:
    def __init__(self):
        self.calls = []

    def spawn_for_assignment(self, **kwargs):
        self.calls.append(kwargs)
        return None


class _LogRecorder:
    def __init__(self):
        self.lines = []

    def info(self, msg, *args):
        self.lines.append(msg % args if args else msg)

    def warning(self, msg, *args):
        self.lines.append(msg % args if args else msg)


def _make_base_session(base_dir, session_id="base", content="WARM_BASE_CONTENT"):
    """Erzeugt eine realistische pi-Session-Datei im Base-Dir."""
    base_dir = Path(base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    f = base_dir / "2026-01-01T00-00-00-000Z_base.jsonl"
    lines = [
        json.dumps({"type": "session", "version": 3, "id": session_id,
                    "timestamp": "2026-01-01T00:00:00.000Z", "cwd": "/tmp"}),
        json.dumps({"type": "user", "content": content}),
    ]
    f.write_text("\n".join(lines))
    return f


def _seeded_file(task_dir, session_id):
    cands = list(Path(task_dir).glob(f"*_{session_id}.jsonl"))
    return cands[0] if cands else None


# ---------------------------------------------------------------------------
# copy_base_to_task (Kern-Logik, pi-konform)
# ---------------------------------------------------------------------------

def test_copy_on_start_atomic():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "base_dir"
        _make_base_session(base, "base", "WARM_BASE_CONTENT")
        task_dir = Path(tmp) / "run" / "task_dir"
        ok = SessionRegistry.copy_base_to_task(base, task_dir, "firma_run_task_CODER", cap_mb=0)
        assert ok is True, "Seed erfolgreich"
        seeded = _seeded_file(task_dir, "firma_run_task_CODER")
        assert seeded is not None, "Task-Session geseedet"
        obj = json.loads(seeded.read_text().splitlines()[0])
        assert obj["id"] == "firma_run_task_CODER", "interne id auf target umgeschrieben"
        assert "WARM_BASE_CONTENT" in seeded.read_text(), "Base-Inhalt uebertragen"


def test_base_immutable():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "base_dir"
        _make_base_session(base, "base", "BASE_ORIGINAL")
        task_dir = Path(tmp) / "run"
        SessionRegistry.copy_base_to_task(base, task_dir, "sid1")
        seeded = _seeded_file(task_dir, "sid1")
        seeded.write_text(seeded.read_text() + '\n{"type":"user","content":"TASK_MUTATED"}')
        base_file = _seeded_file(base, "base")
        assert "BASE_ORIGINAL" in base_file.read_text(), "Base-Inhalt erhalten"
        assert "TASK_MUTATED" not in base_file.read_text(), "Base darf nicht mutieren"


def test_bleed_prevention():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "base_dir"
        _make_base_session(base, "base", "WARM_BASE")
        run = Path(tmp) / "run"
        SessionRegistry.copy_base_to_task(base, run, "sid_task1")
        s1 = _seeded_file(run, "sid_task1")
        s1.write_text(s1.read_text() + '\n{"type":"user","content":"T1SECRET"}')
        SessionRegistry.copy_base_to_task(base, run, "sid_task2")
        s2 = _seeded_file(run, "sid_task2")
        assert "T1SECRET" not in s2.read_text(), "Task2 darf Task1-Geheimnis nicht sehen"
        assert "WARM_BASE" in s2.read_text()
        assert json.loads(s1.read_text().splitlines()[0])["id"] == "sid_task1"
        assert json.loads(s2.read_text().splitlines()[0])["id"] == "sid_task2"


def test_cap_fallback():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "base_dir"
        base.mkdir()
        (base / "2026-01-01T00-00-00-000Z_base.jsonl").write_bytes(b"x" * (3 * 1024 * 1024))
        task_dir = Path(tmp) / "run"
        ok = SessionRegistry.copy_base_to_task(base, task_dir, "sid", cap_mb=1)
        assert ok is False, "Cap ueberschritten -> Fail-safe Fallback"
        assert _seeded_file(task_dir, "sid") is None, "Kein Seed bei Cap-Ueberschreitung"


# ---------------------------------------------------------------------------
# Wiring: Gate seeded bei SESSION_MODE=persona_base
# ---------------------------------------------------------------------------

def test_persona_base_wiring_seeds_task_session():
    saved = {
        "SESSION_MODE": run_pi_mesh.SESSION_MODE,
        "REG_BASE": SessionRegistry.BASE_SESSION_DIR,
        "REG_SESSION": SessionRegistry.SESSION_DIR,
        "LOGGER": run_pi_mesh.logger,
    }
    with tempfile.TemporaryDirectory() as tmp:
        SessionRegistry.BASE_SESSION_DIR = Path(tmp) / "bases"
        SessionRegistry.SESSION_DIR = Path(tmp) / "sessions"
        run_pi_mesh.SESSION_MODE = "persona_base"
        base_dir = SessionRegistry.base_session_dir_for("coding", "default", "CODER")
        _make_base_session(base_dir, "base", "WARM_BASE_SEEDED")
        rec = _LogRecorder()
        run_pi_mesh.logger = rec
        try:
            transport = FakeTransport()
            provider = FakeProvider()
            cb, _ = run_pi_mesh.make_pimesh_messenger_callback(
                transport=transport, provider=provider,
                crew_cwds={"CODER": "pimesh/coding-crew"},
                project_root=".", models={"CODER": None},
            )
            asyncio.run(
                cb(
                    {
                        "role": "CODER",
                        "task_id": "t1",
                        "run_id": "r1",
                        "state_revision": 1,
                        "task_definition": {},
                    }
                )
            )
            calls = provider.calls
            assert calls[0]["session_id"] is not None, "persona_base setzt session_id"
            task_dir = SessionRegistry.SESSION_DIR / "r1"
            seeded = _seeded_file(task_dir, calls[0]["session_id"])
            assert seeded is not None, "persona_base muss Task-Session seeden"
            assert "WARM_BASE_SEEDED" in seeded.read_text()
            assert json.loads(seeded.read_text().splitlines()[0])["id"] == calls[0]["session_id"]
        finally:
            run_pi_mesh.SESSION_MODE = saved["SESSION_MODE"]
            SessionRegistry.BASE_SESSION_DIR = saved["REG_BASE"]
            SessionRegistry.SESSION_DIR = saved["REG_SESSION"]
            run_pi_mesh.logger = saved["LOGGER"]


if __name__ == "__main__":
    test_copy_on_start_atomic()
    test_base_immutable()
    test_bleed_prevention()
    test_cap_fallback()
    test_persona_base_wiring_seeds_task_session()
    print("ALL TESTS PASSED")
