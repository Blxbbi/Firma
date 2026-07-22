"""
Unit-Test fuer PiMeshReceiverLoop._inline_plan_draft (plan_draft side-file recovery).

Covers:
  - Recovery from plan_draft.<task_id>.json (canonical name)
  - Recovery from plan_draft.json (fallback, no task_id suffix)
  - No recovery when plan_draft already embedded in response
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from run_pi_mesh import PiMeshReceiverLoop, WORKER_RESPONSE_SUFFIX


def _write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _make_receiver(crew_cwd: str, run_id: str) -> PiMeshReceiverLoop:
    return PiMeshReceiverLoop(
        transport=None,
        crew_cwds={"PLANNER": crew_cwd},
        project_root=crew_cwd,
        expected_run_id=run_id,
    )


def test_inline_plan_draft_from_canonical_sidefile():
    crew_cwd = tempfile.mkdtemp()
    run_id = "run-plan-1"
    task_id = "task-planner-1"

    worker_dir = os.path.join(crew_cwd, ".pi", "messenger", "crew")
    os.makedirs(worker_dir, exist_ok=True)

    plan_data = {"plan_name": "test-plan", "tasks": []}
    _write(os.path.join(worker_dir, f"plan_draft.{task_id}.json"), json.dumps(plan_data))

    payload = {
        "event": "PLAN_SUBMITTED",
        "task_id": task_id,
        "run_id": run_id,
        "state_revision": 1,
        "artifacts": [],
    }

    receiver = _make_receiver(crew_cwd, run_id)
    receiver._inline_plan_draft(crew_cwd, task_id, payload)

    assert payload.get("plan_draft") == plan_data
    print("PASS: inline plan_draft from canonical sidefile")
    return crew_cwd


def test_inline_plan_draft_from_fallback_plan_draft_json():
    crew_cwd = tempfile.mkdtemp()
    run_id = "run-plan-2"
    task_id = "task-planner-2"

    worker_dir = os.path.join(crew_cwd, ".pi", "messenger", "crew")
    os.makedirs(worker_dir, exist_ok=True)

    plan_data = {"plan_name": "fallback-plan", "tasks": []}
    _write(os.path.join(worker_dir, "plan_draft.json"), json.dumps(plan_data))

    payload = {
        "event": "PLAN_SUBMITTED",
        "task_id": task_id,
        "run_id": run_id,
        "state_revision": 1,
        "artifacts": [],
    }

    receiver = _make_receiver(crew_cwd, run_id)
    receiver._inline_plan_draft(crew_cwd, task_id, payload)

    assert payload.get("plan_draft") == plan_data
    print("PASS: inline plan_draft from fallback plan_draft.json")
    return crew_cwd


def test_inline_plan_draft_skips_when_already_present():
    crew_cwd = tempfile.mkdtemp()
    run_id = "run-plan-3"
    task_id = "task-planner-3"

    worker_dir = os.path.join(crew_cwd, ".pi", "messenger", "crew")
    os.makedirs(worker_dir, exist_ok=True)

    embedded = {"plan_name": "embedded", "tasks": []}
    _write(os.path.join(worker_dir, f"plan_draft.{task_id}.json"), json.dumps({"plan_name": "side", "tasks": []}))

    payload = {
        "event": "PLAN_SUBMITTED",
        "task_id": task_id,
        "run_id": run_id,
        "state_revision": 1,
        "artifacts": [],
        "plan_draft": embedded,
    }

    receiver = _make_receiver(crew_cwd, run_id)
    receiver._inline_plan_draft(crew_cwd, task_id, payload)

    assert payload.get("plan_draft") == embedded
    print("PASS: inline plan_draft skips when already present")
    return crew_cwd


if __name__ == "__main__":
    failures = 0
    for fn in [
        test_inline_plan_draft_from_canonical_sidefile,
        test_inline_plan_draft_from_fallback_plan_draft_json,
        test_inline_plan_draft_skips_when_already_present,
    ]:
        try:
            fn()
        except AssertionError as e:
            print(f"FAIL: {fn.__name__}: {e}")
            failures += 1
        except Exception as e:
            print(f"FAIL: {fn.__name__}: unexpected {type(e).__name__}: {e}")
            failures += 1

    if failures:
        print(f"\n{failures} test(s) failed")
        sys.exit(1)
    print("\nAll tests passed")
