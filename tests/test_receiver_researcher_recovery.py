"""
Unit-Test fuer PiMeshReceiverLoop._recover_researcher_response (Bug F5 Fallback).

Run via: ./tools/safe_test.sh tests/test_receiver_researcher_recovery.py

Covers:
  - Recovery triggert, wenn brief.md vorhanden und worker_response fehlt.
  - Kein Recovery, wenn brief.md fehlt.
  - Kein Recovery, wenn Rolle nicht RESEARCHER ist (project/ fehlt).
  - Response enthaelt RECOVERED_BY_KERNEL-Marker und RESEARCH_COMPLETE.
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


def _recover(crew_cwd: str, run_id: str) -> None:
    receiver = PiMeshReceiverLoop(
        transport=None,
        crew_cwds={"RESEARCHER": crew_cwd},
        project_root=crew_cwd,
        expected_run_id=run_id,
    )
    receiver._recover_researcher_response(crew_cwd)


def test_recovery_triggers_for_researcher_with_brief():
    crew_cwd = tempfile.mkdtemp()
    run_id = "run-recover-1"
    task_id = "task-researcher-1"

    # Layout: crew_cwd/.pi/work/<run_id>/<task_id>/project/ (Dummy)
    work_dir = os.path.join(crew_cwd, ".pi", "work", run_id, task_id)
    os.makedirs(os.path.join(work_dir, "project"), exist_ok=True)

    # Brief vorhanden, keine worker_response
    worker_dir = os.path.join(crew_cwd, ".pi", "messenger", "crew")
    os.makedirs(os.path.join(worker_dir, "tasks"), exist_ok=True)
    _write(
        os.path.join(worker_dir, "tasks", f"{task_id}.json"),
        json.dumps({"id": task_id, "role": "RESEARCHER"}),
    )
    _write(os.path.join(worker_dir, "research", "brief.md"), "# Brief")
    resp_path = os.path.join(crew_cwd, ".pi", "messenger", "crew", f"worker_response.{task_id}{WORKER_RESPONSE_SUFFIX}")
    _write(resp_path, "PLACEHOLDER")  # will be overwritten by recovery
    os.remove(resp_path)

    _recover(crew_cwd, run_id)

    assert os.path.isfile(resp_path), "worker_response missing after recovery"
    with open(resp_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["event"] == "RESEARCH_COMPLETE"
    assert data["sender_role"] == "RESEARCHER"
    assert data["task_id"] == task_id
    assert data["run_id"] == run_id
    assert data["artifacts"] == [{"path": "research/brief.md", "action": "CREATE", "content": None}]
    logs = data.get("logs", "")
    assert "RECOVERED_BY_KERNEL=true" in logs, f"missing recovery marker in logs: {logs}"
    print("PASS: recovery triggers for researcher with brief")
    return crew_cwd


def test_no_recovery_when_brief_missing():
    crew_cwd = tempfile.mkdtemp()
    run_id = "run-recover-2"
    task_id = "task-researcher-2"

    work_dir = os.path.join(crew_cwd, ".pi", "work", run_id, task_id)
    os.makedirs(os.path.join(work_dir, "project"), exist_ok=True)

    resp_path = os.path.join(crew_cwd, ".pi", "messenger", "crew", f"worker_response.{task_id}{WORKER_RESPONSE_SUFFIX}")

    _recover(crew_cwd, run_id)

    assert not os.path.exists(resp_path), "unexpected worker_response created without brief"
    print("PASS: no recovery when brief missing")
    return crew_cwd


def test_no_recovery_when_role_not_researcher():
    crew_cwd = tempfile.mkdtemp()
    run_id = "run-recover-3"
    task_id = "task-coder-1"

    # Layout ohne project/ -> kein Researcher-Task
    work_dir = os.path.join(crew_cwd, ".pi", "work", run_id, task_id)
    os.makedirs(work_dir, exist_ok=True)

    _write(os.path.join(crew_cwd, "research", "brief.md"), "# Brief")
    resp_path = os.path.join(crew_cwd, ".pi", "messenger", "crew", f"worker_response.{task_id}{WORKER_RESPONSE_SUFFIX}")

    # Explicitly write a non-researcher task json so the role guard is exercised.
    worker_dir = os.path.join(crew_cwd, ".pi", "messenger", "crew")
    os.makedirs(os.path.join(worker_dir, "tasks"), exist_ok=True)
    _write(
        os.path.join(worker_dir, "tasks", f"{task_id}.json"),
        json.dumps({"id": task_id, "role": "CODER"}),
    )

    _recover(crew_cwd, run_id)

    assert not os.path.exists(resp_path), "unexpected worker_response created for non-researcher task"
    print("PASS: no recovery when role is not researcher")
    return crew_cwd


def test_no_recovery_for_planner_even_with_brief():
    """Race-Guard: PLANNER task must not be recovered as RESEARCHER."""
    crew_cwd = tempfile.mkdtemp()
    run_id = "run-recover-5"
    task_id = "task-planner-1"

    work_dir = os.path.join(crew_cwd, ".pi", "work", run_id, task_id)
    os.makedirs(os.path.join(work_dir, "project"), exist_ok=True)

    worker_dir = os.path.join(crew_cwd, ".pi", "messenger", "crew")
    _write(os.path.join(worker_dir, "research", "brief.md"), "# Brief")
    resp_path = os.path.join(worker_dir, f"worker_response.{task_id}{WORKER_RESPONSE_SUFFIX}")

    os.makedirs(os.path.join(worker_dir, "tasks"), exist_ok=True)
    _write(
        os.path.join(worker_dir, "tasks", f"{task_id}.json"),
        json.dumps({"id": task_id, "role": "PLANNER"}),
    )

    _recover(crew_cwd, run_id)

    assert not os.path.exists(resp_path), \
        "unexpected worker_response created for planner task (role mismatch)"
    print("PASS: no recovery for planner even with brief")
    return crew_cwd


def test_recovery_skips_existing_response():
    crew_cwd = tempfile.mkdtemp()
    run_id = "run-recover-4"
    task_id = "task-researcher-4"

    work_dir = os.path.join(crew_cwd, ".pi", "work", run_id, task_id)
    os.makedirs(os.path.join(work_dir, "project"), exist_ok=True)

    _write(os.path.join(crew_cwd, "research", "brief.md"), "# Brief")
    resp_path = os.path.join(crew_cwd, ".pi", "messenger", "crew", f"worker_response.{task_id}{WORKER_RESPONSE_SUFFIX}")
    _write(resp_path, '{"event": "RESEARCH_COMPLETE"}')

    _recover(crew_cwd, run_id)

    with open(resp_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["event"] == "RESEARCH_COMPLETE"
    assert "RECOVERED_BY_KERNEL" not in data.get("logs", "")
    print("PASS: recovery skips existing response")
    return crew_cwd


if __name__ == "__main__":
    failures = 0
    for fn in [
        test_recovery_triggers_for_researcher_with_brief,
        test_no_recovery_when_brief_missing,
        test_no_recovery_when_role_not_researcher,
        test_no_recovery_for_planner_even_with_brief,
        test_recovery_skips_existing_response,
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
