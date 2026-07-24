"""
Unit-Tests fuer Receiver Guards (fail-fast + no-progress).

Testet:
 - WORKER_EXITED_WITHOUT_SUBMISSION wenn agent_end in worker.log und keine worker_response
 - NO_PROGRESS wenn nach NO_PROGRESS_TIMEOUT_S keine worker_response und kein write tool call
 - Kein Guard wenn worker_response bereits existiert
"""
import json
import os
import sys
import tempfile
import time
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from run_pi_mesh import PiMeshReceiverLoop, WORKER_RESPONSE_SUFFIX


class FakeTransport:
    def __init__(self):
        self.published = []

    async def publish_response(self, role, payload, correlation_id):
        self.published.append({
            "role": role,
            "payload": payload,
            "correlation_id": correlation_id,
        })


def _write_worker_log(worker_dir, run_id, task_id, events):
    log_path = os.path.join(worker_dir, '.pi', 'work', run_id, task_id, 'worker.log')
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, 'w', encoding='utf-8') as f:
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False) + '\n')


def _make_receiver(run_id='run-X', now=None):
    transport = FakeTransport()
    crew_cwds = {"CODER": 'pimesh/coding-crew'}
    root = tempfile.mkdtemp()
    receiver = PiMeshReceiverLoop(
        transport=transport,
        crew_cwds=crew_cwds,
        project_root=root,
        expected_run_id=run_id,
        task_assigned_at={'task-1': ('CODER', now if now is not None else time.time())},
    )
    return transport, receiver, root


def test_fail_fast_on_agent_end_without_worker_response():
    transport, receiver, root = _make_receiver()
    crew_cwd = os.path.join(root, 'pimesh/coding-crew')
    _write_worker_log(crew_cwd, 'run-X', 'task-1', [
        {"type": "session"},
        {"type": "agent_end", "willRetry": False},
    ])
    # Keine worker_response schreiben -> simuliert Crash/Exit ohne Submission
    out = receiver.scan_once()
    events = [it['payload']['event'] for it in out]
    assert 'TASK_FAILED' in events, f"expected TASK_FAILED, got {events}"
    fail = [it for it in out if it['payload']['event'] == 'TASK_FAILED'][0]
    assert 'WORKER_EXITED_WITHOUT_SUBMISSION' in fail['payload']['logs']
    assert fail['role'] == 'CODER'
    print("PASS: fail-fast on agent_end without worker_response")


def test_no_guard_when_worker_response_exists():
    transport, receiver, root = _make_receiver()
    crew_cwd = os.path.join(root, 'pimesh/coding-crew')
    worker_dir = os.path.join(crew_cwd, '.pi', 'messenger', 'crew')
    os.makedirs(worker_dir, exist_ok=True)
    resp = {
        "protocol_version": "1.0",
        "message_id": "resp-1",
        "task_id": "task-1",
        "run_id": "run-X",
        "state_revision": 1,
        "event": "CODE_SUBMITTED",
        "sender_role": "CODER",
        "timestamp": "2026-01-01T00:00:00+00:00",
        "logs": "",
        "artifacts": [],
        "plan_draft": None,
    }
    with open(os.path.join(worker_dir, f'worker_response.task-1{WORKER_RESPONSE_SUFFIX}'), 'w', encoding='utf-8') as f:
        json.dump(resp, f)
    out = receiver.scan_once()
    events = [it['payload']['event'] for it in out]
    assert 'TASK_FAILED' not in events
    assert 'WORKER_TIMEOUT' not in events
    print("PASS: no guard when worker_response exists")


def test_no_progress_timeout_triggers_before_hard_timeout():
    old_time = time.time() - 130  # älter als 120s NO_PROGRESS_TIMEOUT_S
    transport, receiver, root = _make_receiver(now=old_time)
    crew_cwd = os.path.join(root, 'pimesh/coding-crew')
    # Keine worker_response, kein agent_end, keine write tool calls
    out = receiver.scan_once()
    events = [it['payload']['event'] for it in out]
    assert 'WORKER_TIMEOUT' in events, f"expected WORKER_TIMEOUT, got {events}"
    timeout = [it for it in out if it['payload']['event'] == 'WORKER_TIMEOUT'][0]
    assert 'NO_PROGRESS' in timeout['payload']['logs']
    assert timeout['role'] == 'CODER'
    print("PASS: no-progress timeout triggers before hard timeout")


if __name__ == "__main__":
    test_fail_fast_on_agent_end_without_worker_response()
    test_no_guard_when_worker_response_exists()
    test_no_progress_timeout_triggers_before_hard_timeout()
    print("\nALL RECEIVER GUARD TESTS PASSED")
