"""Phase 6.3 P1 — Spawn-Serialisierung (Concurrency-Limiter) + Modell-Pinning.

Beweist:
- asyncio.Semaphore begrenzt gleichzeitige pi-Spawns (max concurrent == N).
- PiProvider emittiert --provider/--model nur bei explizitem FIRMA_MODEL_* (= provider/model).

Lauf: python tests/test_p1_spawn_limits.py
"""
import asyncio
import os
import subprocess
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_pi_mesh
from engine.providers import pi_provider


class FakeTransport:
    async def dispatch(self, payload, review_artifacts=None):
        self.dispatched = payload

    async def publish_response(self, role=None, payload=None, correlation_id=None):
        pass


class FakeProc:
    def __init__(self, provider):
        self.provider = provider
        self._done = threading.Event()
        # Selbst-Freigabe: verhindert Deadlock, wenn der Test die Proc nicht
        # explizit freigibt (z.B. Semaphor=1 + mehrere Tasks, deren Proc erst
        # NACH dem Release-Sweep erzeugt wird). Garantiert, dass der Semaphor
        # immer wieder frei wird -> kein Haengen des asyncio-Loops.
        self._timer = threading.Timer(0.05, self._fire)
        self._timer.daemon = True
        self._timer.start()

    def _fire(self):
        if not self._done.is_set():
            self.provider.active -= 1
            self._done.set()

    def wait(self):
        self._done.wait()
        return 0

    def release(self):
        self._fire()


class StubProvider:
    def __init__(self):
        self.active = 0
        self.max_active = 0
        self.procs = []

    def spawn_for_assignment(self, **kwargs):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        proc = FakeProc(self)
        self.procs.append(proc)
        return proc


def _set_modes(mode, max_spawns, reviewer_dummy=True, reject_once=False):
    saved = {
        "SESSION_MODE": run_pi_mesh.SESSION_MODE,
        "MAX_CONCURRENT_SPAWNS": run_pi_mesh.MAX_CONCURRENT_SPAWNS,
        "REVIEWER_IS_DUMMY": run_pi_mesh.REVIEWER_IS_DUMMY,
        "REVIEWER_DUMMY_REJECT_ONCE": run_pi_mesh.REVIEWER_DUMMY_REJECT_ONCE,
    }
    run_pi_mesh.SESSION_MODE = mode
    run_pi_mesh.MAX_CONCURRENT_SPAWNS = max_spawns
    run_pi_mesh.REVIEWER_IS_DUMMY = reviewer_dummy
    run_pi_mesh.REVIEWER_DUMMY_REJECT_ONCE = reject_once
    return saved


def _restore(saved):
    for k, v in saved.items():
        setattr(run_pi_mesh, k, v)


def _drive_three(cb, provider):
    async def drive():
        await asyncio.gather(
            cb({"role": "CODER", "task_id": "t1", "run_id": "r1", "state_revision": 1, "task_definition": {}}),
            cb({"role": "CODER", "task_id": "t2", "run_id": "r1", "state_revision": 1, "task_definition": {}}),
            cb({"role": "CODER", "task_id": "t3", "run_id": "r1", "state_revision": 1, "task_definition": {}}),
        )
        await asyncio.sleep(0.15)  # kurz: alle 3 "gestartet", aber Semaphor greift
        peak = provider.max_active
        for p in provider.procs:
            p.release()
        await asyncio.sleep(0.15)
        return peak
    return asyncio.run(drive())


def test_spawn_serialization_limits_concurrency():
    saved = _set_modes("off", 1)
    provider = StubProvider()
    try:
        transport = FakeTransport()
        cb, _ = run_pi_mesh.make_pimesh_messenger_callback(
            transport=transport, provider=provider,
            crew_cwds={"PLANNER": "x", "CODER": "y"}, project_root=".", models={},
        )
        peak = _drive_three(cb, provider)
        assert peak <= 1, f"max concurrent erwartet <=1, war {peak}"
    finally:
        _restore(saved)


def test_spawn_serialization_allows_n_concurrent():
    saved = _set_modes("off", 2)
    provider = StubProvider()
    try:
        transport = FakeTransport()
        cb, _ = run_pi_mesh.make_pimesh_messenger_callback(
            transport=transport, provider=provider,
            crew_cwds={"PLANNER": "x", "CODER": "y"}, project_root=".", models={},
        )
        peak = _drive_three(cb, provider)
        assert peak <= 2, f"max concurrent erwartet <=2, war {peak}"
    finally:
        _restore(saved)


def test_pi_provider_does_not_emit_model_flags_when_unset():
    p = pi_provider.PiProvider()
    args = p.build_args("prompt", model=None, provider=None)
    assert "--model" not in args and "--provider" not in args


def test_pi_provider_emits_model_flags_when_set():
    p = pi_provider.PiProvider()
    args = p.build_args("prompt", model="kat-coder-pro", provider="kilo")
    assert "--provider" in args and "kilo" in args
    assert "--model" in args and "kat-coder-pro" in args


def test_spawn_for_assignment_emits_model_flags():
    captured = {}

    class FakePopen:
        def __init__(self, args, **kw):
            captured["args"] = list(args)

        def wait(self):
            return 0

        def kill(self):
            pass

    saved = subprocess.Popen
    subprocess.Popen = FakePopen
    try:
        p = pi_provider.PiProvider()
        p.spawn_for_assignment(
            role="CODER", task_id="t1", run_id="r1", state_revision=1,
            crew_cwd=".", model="kilo/kat-coder-pro",
        )
    finally:
        subprocess.Popen = saved
    a = captured["args"]
    assert "--provider" in a and a[a.index("--provider") + 1] == "kilo"
    assert "--model" in a and a[a.index("--model") + 1] == "kat-coder-pro"


if __name__ == "__main__":
    test_spawn_serialization_limits_concurrency()
    test_spawn_serialization_allows_n_concurrent()
    test_pi_provider_does_not_emit_model_flags_when_unset()
    test_pi_provider_emits_model_flags_when_set()
    test_spawn_for_assignment_emits_model_flags()
    print("ALL TESTS PASSED")
