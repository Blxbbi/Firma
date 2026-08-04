"""Phase 6.1: PiProvider session-flag wiring (deterministic, no network)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.providers.pi_provider import PiProvider


def _provider():
    return PiProvider(provider=None, model=None)


def test_build_args_deterministic_uses_no_session():
    args = _provider().build_args("do work")
    assert "--no-session" in args
    assert "--session-id" not in args
    assert "--session-dir" not in args
    assert "-p" in args


def test_build_args_collaborative_uses_session_flags():
    args = _provider().build_args(
        "do work", session_id="firma_run_t_coder", session_dir="/tmp/sess/run"
    )
    assert "--session-id" in args
    assert args[args.index("--session-id") + 1] == "firma_run_t_coder"
    assert "--session-dir" in args
    assert args[args.index("--session-dir") + 1] == "/tmp/sess/run"
    # KEIN --no-session im collaborative Modus!
    assert "--no-session" not in args


def test_normalize_extension_dir_replaces_backslashes():
    p = _provider()
    assert p._normalize_extension_dir(r"C:\Users\arthu\.pi\agent\npm\node_modules\pi-messenger") == "C:/Users/arthu/.pi/agent/npm/node_modules/pi-messenger"


def test_spawn_for_assignment_normalizes_extension_dir():
    p = _provider()
    captured = {}

    def fake_spawn_worker(crew_cwd, prompt, model=None, provider=None,
                          session_id=None, session_dir=None, log_path=None):
        captured["session_id"] = session_id
        captured["session_dir"] = session_dir
        captured["prompt"] = prompt
        captured["log_path"] = log_path

        class _P:
            pass

        return _P()

    orig = p.spawn_worker
    p.spawn_worker = fake_spawn_worker
    try:
        p.spawn_for_assignment(
            role="CODER", task_id="task-1", run_id="run-1", state_revision=2,
            crew_cwd="/tmp/crew", model="kilo/kilo",
            session_id="firma_run-1_task-1_CODER", session_dir="/tmp/sess/run-1",
        )
    finally:
        p.spawn_worker = orig
    assert captured["session_id"] == "firma_run-1_task-1_CODER"
    assert captured["session_dir"] == "/tmp/sess/run-1"
    assert "prompt.txt" in captured["prompt"]  # V1: prompt is now a file reference
    assert captured["log_path"] is not None


def test_spawn_for_assignment_normalizes_extension_dir_in_args():
    p = _provider()
    # Verify build_args normalizes extension dir
    args = p.build_args("test", model="kilo/kilo", session_id="sid", session_dir="/tmp/sess")
    # Find --extension arg
    ext_idx = args.index("--extension")
    ext_path = args[ext_idx + 1]
    # Should use forward slashes
    assert "\\" not in ext_path
    assert "/" in ext_path
    assert ext_path == "C:/Users/arthu/.pi/agent/npm/node_modules/pi-messenger"


if __name__ == "__main__":
    test_build_args_deterministic_uses_no_session()
    test_build_args_collaborative_uses_session_flags()
    test_normalize_extension_dir_replaces_backslashes()
    test_spawn_for_assignment_normalizes_extension_dir()
    test_spawn_for_assignment_normalizes_extension_dir_in_args()
    print("ALL TESTS PASSED")
