"""Phase 6.1: Spec-Feedback-Block in der CODER-Spec (deterministic)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.transport.pi_mesh_transport import PiMeshTransport


def _spec(task_definition):
    t = PiMeshTransport(crew_cwds={}, project_root="/tmp")
    payload = {
        "task_id": "task-1",
        "run_id": "run-1",
        "role": "CODER",
        "state_revision": 2,
        "prompt": "Build a snake game",
        "task_definition": task_definition,
    }
    return t._build_spec_markdown(payload)


def test_spec_includes_feedback_when_present():
    spec = _spec({
        "description": "Build snake",
        "acceptance_criteria": ["EXISTS:game.js"],
        "previous_feedback": "You used textContent but innerHTML is required.",
    })
    assert "REJECTED BY THE REVIEWER" in spec
    assert "FRISCHE" in spec
    assert "textContent but innerHTML is required" in spec
    # assignment JSON should also carry it
    assert "previous_feedback" in spec


def test_spec_omits_feedback_when_absent():
    spec = _spec({
        "description": "Build snake",
        "acceptance_criteria": ["EXISTS:game.js"],
        "previous_feedback": None,
    })
    assert "Previous feedback" not in spec


if __name__ == "__main__":
    test_spec_includes_feedback_when_present()
    test_spec_omits_feedback_when_absent()
    print("ALL TESTS PASSED")
