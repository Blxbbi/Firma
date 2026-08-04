"""Phase 6.3 Stufe 2 — SESSION_MODE=task: Retry-Continuity + Disk-Guards + Observability.

Lokal (Dev) aktiviert via FIRMA_SESSION_MODE=task; Code-Default bleibt 'off'.
Beweist:
- Retry nutzt dieselbe Session-ID (Continuity).
- Disk-Cap wird fail-safe respektiert (spawn OHNE session, kein Crash).
- Spawn-Log enthaelt session_mode + session_id (Observability).

Lauf: python tests/test_session_mode_task.py
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import engine.settings as settings
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


def _run_callback(session_mode, session_dir=None, cap=None, run_id="r1", role="PLANNER"):
    saved = {
        "SESSION_MODE": run_pi_mesh.SESSION_MODE,
        "MAX_CAP": run_pi_mesh.MAX_SESSION_DISK_MB_PER_RUN,
        "REG_SESSION_DIR": SessionRegistry.SESSION_DIR,
        "LOGGER": run_pi_mesh.logger,
    }
    run_pi_mesh.SESSION_MODE = session_mode
    if cap is not None:
        run_pi_mesh.MAX_SESSION_DISK_MB_PER_RUN = cap
    if session_dir is not None:
        SessionRegistry.SESSION_DIR = session_dir
    rec = _LogRecorder()
    run_pi_mesh.logger = rec
    try:
        transport = FakeTransport()
        provider = FakeProvider()
        cb, _spawned, _task_done_events, _task_assigned_at, _task_cooldown = run_pi_mesh.make_pimesh_messenger_callback(
            transport=transport,
            provider=provider,
            crew_cwds={role: "pimesh/planning-crew"},
            project_root=".",
            models={role: None},
        )
        asyncio.run(
            cb(
                {
                    "role": role,
                    "task_id": "t1",
                    "run_id": run_id,
                    "state_revision": 1,
                    "task_definition": {},
                }
            )
        )
        return provider.calls, rec.lines
    finally:
        run_pi_mesh.SESSION_MODE = saved["SESSION_MODE"]
        run_pi_mesh.MAX_SESSION_DISK_MB_PER_RUN = saved["MAX_CAP"]
        SessionRegistry.SESSION_DIR = saved["REG_SESSION_DIR"]
        run_pi_mesh.logger = saved["LOGGER"]


def test_retry_reuses_same_session_id():
    calls1, _ = _run_callback("task", run_id="run-retry")
    calls2, _ = _run_callback("task", run_id="run-retry")
    assert calls1 and calls2
    assert calls1[0]["session_id"] == calls2[0]["session_id"], \
        "Retry muss dieselbe Session-ID nutzen (Continuity)"
    assert calls1[0]["session_id"] is not None


def test_disk_cap_exceeded_spawns_without_session():
    with tempfile.TemporaryDirectory() as tmp:
        run_id = "run-cap1"
        run_dir = Path(tmp) / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "big.bin").write_bytes(b"x" * (2 * 1024 * 1024))  # 2 MB > 1 MB cap
        calls, _ = _run_callback("task", session_dir=Path(tmp), cap=1, run_id=run_id)
        assert calls[0]["session_id"] is None, \
            "Ueber Cap -> spawn OHNE session (fail-safe)"
        assert calls[0]["session_dir"] is None


def test_disk_cap_ok_spawns_with_session():
    with tempfile.TemporaryDirectory() as tmp:
        run_id = "run-cap2"
        run_dir = Path(tmp) / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "small.txt").write_bytes(b"x" * 100)  # tiny
        calls, _ = _run_callback("task", session_dir=Path(tmp), cap=1, run_id=run_id)
        assert calls[0]["session_id"] is not None, \
            "Unter Cap -> session gesetzt"


def test_observability_logs_session_info():
    calls, logs = _run_callback("task", run_id="run-obs")
    assert calls[0]["session_id"] is not None
    joined = "\n".join(logs)
    assert "session_mode=task" in joined, "Observability: session_mode im Log"
    assert ("session_id=" in joined) and (calls[0]["session_id"] in joined), \
        "Observability: session_id im Log"


if __name__ == "__main__":
    test_retry_reuses_same_session_id()
    test_disk_cap_exceeded_spawns_without_session()
    test_disk_cap_ok_spawns_with_session()
    test_observability_logs_session_info()
    print("ALL TESTS PASSED")
