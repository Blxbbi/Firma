"""Phase 6.2: Unit-Test fuer den deterministischen Feedback-Loop-Trigger.

Testet den REVIEWER-Dummy-Bypass in run_pi_mesh.make_pimesh_messenger_callback:
- FIRMA_REVIEWER_DUMMY_REJECT_ONCE=on  -> erster Review (kein previous_feedback)
  -> REVIEW_FAILURE; Retry (previous_feedback gesetzt) -> REVIEW_APPROVED.
- FIRMA_REVIEWER_DUMMY_REJECT_ONCE=off -> immer REVIEW_APPROVED.
(async, keine echten pi-Prozesse; FakeTransport/FakeProvider.)
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_pi_mesh


class FakeTransport:
    def __init__(self):
        self.published = []

    async def publish_response(self, role, payload, correlation_id=None):
        self.published.append((role, payload))


class FakeProvider:
    def __init__(self):
        self.spawns = []

    def spawn_for_assignment(self, **kwargs):
        self.spawns.append(kwargs)
        return None


def _make_wrapper(reject_once):
    run_pi_mesh.REVIEWER_IS_DUMMY = True
    run_pi_mesh.REVIEWER_DUMMY_REJECT_ONCE = reject_once
    transport = FakeTransport()
    provider = FakeProvider()
    wrapper, _spawned, _task_done_events, _task_assigned_at, _task_cooldown = run_pi_mesh.make_pimesh_messenger_callback(
        transport, provider, {"REVIEWER": "pimesh/reviewing-crew"}, "/tmp", {}
    )
    return transport, provider, wrapper


def _review_payload(task_id, rev, feedback=None):
    td = {}
    if feedback is not None:
        td["previous_feedback"] = feedback
    return {
        "task_id": task_id, "run_id": "r1", "state_revision": rev,
        "role": "REVIEWER", "prompt": "p", "task_definition": td,
    }


def test_dummy_reject_once_rejects_first_then_approves_retry():
    transport, provider, wrapper = _make_wrapper(True)
    # erster Review: kein previous_feedback -> REJECT
    asyncio.run(wrapper(_review_payload("task-1", 2, feedback=None)))
    # Retry: previous_feedback gesetzt -> APPROVE
    asyncio.run(wrapper(_review_payload("task-1", 3, feedback="fix step 3")))
    events = [p["event"] for (_, p) in transport.published]
    assert events == ["REVIEW_FAILURE", "REVIEW_APPROVED"], events
    # Dummy-Pfad spawned KEINEN LLM-Prozess
    assert provider.spawns == []


def test_dummy_reject_once_off_always_approves():
    transport, provider, wrapper = _make_wrapper(False)
    asyncio.run(wrapper(_review_payload("task-1", 2, feedback=None)))
    asyncio.run(wrapper(_review_payload("task-1", 3, feedback="fix step 3")))
    events = [p["event"] for (_, p) in transport.published]
    assert events == ["REVIEW_APPROVED", "REVIEW_APPROVED"], events


if __name__ == "__main__":
    test_dummy_reject_once_rejects_first_then_approves_retry()
    test_dummy_reject_once_off_always_approves()
    print("ALL TESTS PASSED")
