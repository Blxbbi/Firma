"""
Unit-Tests fuer die PiMesh messenger_callback (single authority: dispatch + spawn).

Testet die Idempotency-Regel des Users:
 - pro (task_id, state_revision) wird hoechstens EINMAL gespawnt (defense-in-depth)
 - eine neue state_revision (Retry/CAS) erzeugt bewusst einen NEUEN Spawn
"""
import asyncio
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from run_pi_mesh import make_pimesh_messenger_callback

CREWS = {
    "PLANNER": "pimesh/planning-crew",
    "CODER": "pimesh/coding-crew",
    "REVIEWER": "pimesh/reviewing-crew",
}


class FakeTransport:
    def __init__(self):
        self.dispatched = []

    async def dispatch(self, payload, review_artifacts=None):
        self.dispatched.append(payload)


class FakeProvider:
    def __init__(self):
        self.spawns = []

    def spawn_for_assignment(self, **kwargs):
        self.spawns.append(kwargs)


def _payload(task_id, revision):
    return {
        "event": "TASK_ASSIGNMENT", "run_id": "run-X", "task_id": task_id,
        "role": "CODER", "state_revision": revision, "prompt": "p",
        "task_definition": {"description": "d", "acceptance_criteria": ["a"]},
    }


def _make():
    root = tempfile.mkdtemp()
    transport = FakeTransport()
    provider = FakeProvider()
    wrapper, spawned, _task_done_events, task_assigned_at = make_pimesh_messenger_callback(
        transport=transport, provider=provider, crew_cwds=CREWS,
        project_root=root, models={"CODER": "kilo/kilo-auto/free"},
    )
    return transport, provider, wrapper, task_assigned_at


def test_spawn_called_once_per_assignment_revision():
    transport, provider, wrapper, _task_assigned_at = _make()
    p = _payload("task-1", 5)
    asyncio.run(wrapper(p))
    asyncio.run(wrapper(p))  # identischer Emit -> ganze Callback uebersprungen (dispatch + spawn)
    assert len(transport.dispatched) == 1, f"dedupe skippt dispatch, got {len(transport.dispatched)}"
    assert len(provider.spawns) == 1, f"spawn nur einmal pro (task,revision), got {len(provider.spawns)}"
    print("PASS: spawn + dispatch once per assignment revision")


def test_spawn_called_again_on_new_revision():
    transport, provider, wrapper, _task_assigned_at = _make()
    asyncio.run(wrapper(_payload("task-1", 5)))
    asyncio.run(wrapper(_payload("task-1", 6)))  # neue revision -> legitimer Respawn
    assert len(provider.spawns) == 2, f"neue revision respawnt, got {len(provider.spawns)}"
    print("PASS: spawn called again on new revision")


def test_task_assigned_at_tracked():
    _, _, wrapper, task_assigned_at = _make()
    assert len(task_assigned_at) == 0
    asyncio.run(wrapper(_payload("task-1", 5)))
    assert ("task-1", 5) in task_assigned_at
    role, ts = task_assigned_at[("task-1", 5)]
    assert role == "CODER"
    assert ts <= time.time()
    print("PASS: task_assigned_at tracked")


if __name__ == "__main__":
    test_spawn_called_once_per_assignment_revision()
    test_spawn_called_again_on_new_revision()
    test_task_assigned_at_tracked()
    print("\nALL SPAWN TESTS PASSED")
