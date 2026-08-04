"""Phase 6.3 Step 1 — Entkopplung SESSION_MODE / PROCESS_MODE.

Schutz-Invarianten:
- Default SESSION_MODE=off == heute (deterministic, --no-session). Bestehende Runs
  bleiben 100% unveraendert.
- SESSION_MODE=task setzt session_id AUCH wenn FIRMA_MODE=deterministic (Entkopplung).
- Ungueltige Werte fallen auf den sicheren Default (off) zurueck -- kein stilles Aktivieren.
- build_args emittiert korrekt --session-id/--session-dir bzw. --no-session.

Lauf: python tests/test_session_mode_gate.py
"""
import asyncio
import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import engine.settings as settings
from engine.providers.pi_provider import PiProvider
import run_pi_mesh


# ---------------------------------------------------------------------------
# Settings-Achsen
# ---------------------------------------------------------------------------

def test_settings_defaults_preserve_todays_behavior():
    assert settings.SESSION_MODE == "off", "Default SESSION_MODE muss 'off' sein"
    assert settings.PROCESS_MODE == "oneshot", "Default PROCESS_MODE muss 'oneshot' sein"


def test_session_mode_env_and_validation():
    # gueltig: task
    os.environ["FIRMA_SESSION_MODE"] = "task"
    importlib.reload(settings)
    assert settings.SESSION_MODE == "task"
    # ungueltig -> fallback off
    os.environ["FIRMA_SESSION_MODE"] = "garbage"
    importlib.reload(settings)
    assert settings.SESSION_MODE == "off"
    # persona_base gueltig
    os.environ["FIRMA_SESSION_MODE"] = "persona_base"
    importlib.reload(settings)
    assert settings.SESSION_MODE == "persona_base"
    # aufraeumen: Default wiederherstellen
    os.environ.pop("FIRMA_SESSION_MODE", None)
    importlib.reload(settings)
    assert settings.SESSION_MODE == "off"


def test_process_mode_env_and_validation():
    os.environ["FIRMA_PROCESS_MODE"] = "resident"
    importlib.reload(settings)
    assert settings.PROCESS_MODE == "resident"
    os.environ["FIRMA_PROCESS_MODE"] = "bogus"
    importlib.reload(settings)
    assert settings.PROCESS_MODE == "oneshot"
    os.environ.pop("FIRMA_PROCESS_MODE", None)
    importlib.reload(settings)
    assert settings.PROCESS_MODE == "oneshot"


# ---------------------------------------------------------------------------
# pi_provider.build_args — Flag-Emission
# ---------------------------------------------------------------------------

def test_build_args_no_session_when_id_none():
    args = PiProvider().build_args(prompt="do it")
    assert "--no-session" in args
    assert "--session-id" not in args
    assert "--session-dir" not in args


def test_build_args_session_flags_when_id_set():
    args = PiProvider().build_args(
        prompt="do it", session_id="sid123", session_dir="/tmp/sess"
    )
    assert "--session-id" in args and "sid123" in args
    assert "--session-dir" in args and "/tmp/sess" in args
    assert "--no-session" not in args


# ---------------------------------------------------------------------------
# Gate im messenger_callback — Entkopplung bewiesen
# ---------------------------------------------------------------------------

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


def _run_callback(session_mode):
    # monkeypatch des Modul-Globals (Callback liest SESSION_MODE zur Laufzeit)
    orig = run_pi_mesh.SESSION_MODE
    run_pi_mesh.SESSION_MODE = session_mode
    try:
        transport = FakeTransport()
        provider = FakeProvider()
        cb, _spawned, _task_done_events, _task_assigned_at, _task_cooldown = run_pi_mesh.make_pimesh_messenger_callback(
            transport=transport,
            provider=provider,
            crew_cwds={"PLANNER": "pimesh/planning-crew"},
            project_root=".",
            models={"PLANNER": None},
        )
        asyncio.run(
            cb(
                {
                    "role": "PLANNER",
                    "task_id": "t1",
                    "run_id": "r1",
                    "state_revision": 1,
                    "task_definition": {},
                }
            )
        )
        return provider.calls
    finally:
        run_pi_mesh.SESSION_MODE = orig


def test_session_gate_off_emits_no_session_flags():
    # Default-Verhalten: kein session_id -> build_args emittiert --no-session
    calls = _run_callback("off")
    assert calls, "spawn_for_assignment wurde nicht aufgerufen"
    assert calls[0]["session_id"] is None
    assert calls[0]["session_dir"] is None


def test_session_gate_task_emits_session_flags_even_if_firma_mode_deterministic():
    # Entkopplung: SESSION_MODE=task aktiviert Session AUCH bei deterministic.
    calls = _run_callback("task")
    assert calls, "spawn_for_assignment wurde nicht aufgerufen"
    assert calls[0]["session_id"] is not None, \
        "SESSION_MODE=task muss session_id setzen (unabhaengig von FIRMA_MODE)"
    assert calls[0]["session_dir"] is not None


if __name__ == "__main__":
    test_settings_defaults_preserve_todays_behavior()
    test_session_mode_env_and_validation()
    test_process_mode_env_and_validation()
    test_build_args_no_session_when_id_none()
    test_build_args_session_flags_when_id_set()
    test_session_gate_off_emits_no_session_flags()
    test_session_gate_task_emits_session_flags_even_if_firma_mode_deterministic()
    print("ALL TESTS PASSED")
