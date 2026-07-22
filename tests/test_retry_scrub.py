"""Unit-Tests fuer Phase 6.2 Fix 1 (Retry-Session-Scrub) und Fix 2 (Eskalations-Cap).

Fix 1: CODER-Retry darf nicht in die eigene "Ich bin fertig"-Session laufen.
  - PiProvider.build_assignment_prompt fuegt bei Retry ein OVERRIDE an.
  - PiMeshTransport._build_spec_markdown rendert bei previous_feedback eine
    "REJECTED BY THE REVIEWER"-Preamble.
  - _scrub_retry_response loescht die stale worker_response-Datei vor dem Retry.
"""
import os
import tempfile
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.providers.pi_provider import PiProvider
from engine.transport.pi_mesh_transport import PiMeshTransport, WORKER_RESPONSE_SUFFIX
from run_pi_mesh import _scrub_retry_response


def test_build_assignment_prompt_plain():
    p = PiProvider.build_assignment_prompt("task-2")
    assert "task-2.md" in p
    assert "OVERRIDE" not in p


def test_build_assignment_prompt_with_correction():
    note = "OVERRIDE: Dein vorheriger Versuch wurde ABGELEHNT."
    p = PiProvider.build_assignment_prompt("task-2", correction_note=note)
    assert note in p
    assert p.startswith("Read the file")


def _coder_retry_payload(feedback="fix the markup"):
    return {
        "task_id": "task-2",
        "run_id": "run-x",
        "role": "CODER",
        "state_revision": 2,
        "prompt": "build snake",
        "task_definition": {
            "description": "Implement style.css",
            "acceptance_criteria": ["EXISTS:style.css"],
            "previous_feedback": feedback,
        },
    }


def test_spec_has_reject_preamble_on_retry():
    t = PiMeshTransport(crew_cwds={}, project_root=".")
    md = t._build_spec_markdown(_coder_retry_payload())
    assert "REJECTED BY THE REVIEWER" in md
    assert "FRISCHE" in md
    assert "fix the markup" in md


def test_spec_no_reject_preamble_on_first_attempt():
    t = PiMeshTransport(crew_cwds={}, project_root=".")
    payload = _coder_retry_payload()
    payload["task_definition"] = {k: v for k, v in payload["task_definition"].items() if k != "previous_feedback"}
    md = t._build_spec_markdown(payload)
    assert "REJECTED BY THE REVIEWER" not in md


def test_scrub_retry_response_deletes_stale_file():
    with tempfile.TemporaryDirectory() as d:
        worker_dir = os.path.join(d, ".pi", "messenger", "crew")
        os.makedirs(worker_dir)
        stale = os.path.join(worker_dir, f"worker_response.task-2{WORKER_RESPONSE_SUFFIX}")
        with open(stale, "w") as f:
            f.write('{"event":"CODE_SUBMITTED"}')
        assert os.path.exists(stale)
        removed = _scrub_retry_response(d, "task-2")
        assert removed is True
        assert not os.path.exists(stale)


def test_scrub_retry_response_no_file_returns_false():
    with tempfile.TemporaryDirectory() as d:
        removed = _scrub_retry_response(d, "task-9")
        assert removed is False


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
    sys.exit(0 if passed == len(tests) else 1)
