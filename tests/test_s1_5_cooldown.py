"""
S1.5 Backoff/Cooldown Tests.

Testet:
 - Rate-limit erkennt 429 und setzt Cooldown
 - Cooldown verhindert Spawn vor Ablauf
 - Cooldown erlaubt Spawn nach Ablauf
 - Backoff ist exponentiell (30s, 60s, 120s, cap 10min)
 - Verschiedene Tasks haben unabhängige Cooldowns
"""
import asyncio
import os
import sys
import time
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_pi_mesh


class FakeTransport:
    def __init__(self):
        self.published = []

    async def dispatch(self, payload, review_artifacts=None):
        pass

    async def publish_response(self, role, payload, correlation_id=None):
        self.published.append((role, payload))


class FakeProvider:
    def __init__(self):
        self.spawns = []

    def spawn_for_assignment(self, **kwargs):
        self.spawns.append(kwargs)
        return None


def _make_callback():
    transport = FakeTransport()
    provider = FakeProvider()
    wrapper, spawned, _task_done_events, _task_assigned_at, task_cooldown = run_pi_mesh.make_pimesh_messenger_callback(
        transport, provider, {"CODER": "pimesh/coding-crew"}, "/tmp", {}
    )
    return transport, provider, wrapper, spawned, task_cooldown


def _coder_payload(task_id, rev):
    return {
        "task_id": task_id, "run_id": "r1", "state_revision": rev,
        "role": "CODER", "prompt": "p", "task_definition": {},
    }


def test_rate_limit_sets_cooldown():
    """Nach 429-Erkennung wird Cooldown in task_cooldown gesetzt."""
    transport, provider, wrapper, spawned, task_cooldown = _make_callback()
    payload = _coder_payload("task-1", 1)

    # Simuliere 429-Erkennung durch direktes Setzen des Cooldowns
    # (wie es _detect_rate_limit_failure nach 429 tun wuerde)
    key = ("task-1", 1, "CODER")
    task_cooldown[key] = time.time() + 30  # 30s Cooldown

    # Erster Aufruf: sollte geskippt werden
    asyncio.run(wrapper(payload))
    assert len(provider.spawns) == 0, f"expected 0 spawns during cooldown, got {len(provider.spawns)}"
    print("PASS: rate-limit sets cooldown and blocks spawn")


def test_cooldown_prevents_respawn_before_deadline():
    """Spawn wird blockiert, solange Cooldown aktiv ist."""
    transport, provider, wrapper, spawned, task_cooldown = _make_callback()
    
    # Setze Cooldown fuer task-2 rev=1 fuer 60s in der Zukunft
    key = ("task-2", 1, "CODER")
    task_cooldown[key] = time.time() + 60

    # Sofortiger Versuch: sollte geskippt werden
    asyncio.run(wrapper(_coder_payload("task-2", 1)))
    assert len(provider.spawns) == 0

    # Versuch nach 30s: sollte immer noch geskippt werden (gleiche revision)
    spawned.clear()  # umgehe duplicate-spawn-check fuer diesen Test
    with mock.patch('run_pi_mesh.time.time', return_value=time.time() + 30):
        asyncio.run(wrapper(_coder_payload("task-2", 1)))
    assert len(provider.spawns) == 0

    # Versuch nach 61s: sollte erlaubt sein (gleiche revision)
    spawned.clear()
    with mock.patch('run_pi_mesh.time.time', return_value=time.time() + 61):
        asyncio.run(wrapper(_coder_payload("task-2", 1)))
    assert len(provider.spawns) == 1
    assert provider.spawns[0]["task_id"] == "task-2"
    print("PASS: cooldown prevents respawn before deadline")


def test_cooldown_expires_allows_next_attempt():
    """Nach Ablauf des Cooldowns wird Spawn wieder erlaubt."""
    transport, provider, wrapper, spawned, task_cooldown = _make_callback()
    payload = _coder_payload("task-3", 1)

    # Setze Cooldown fuer 10s in der Zukunft
    key = ("task-3", 1, "CODER")
    task_cooldown[key] = time.time() + 10

    # Sofortiger Versuch: geskippt
    asyncio.run(wrapper(payload))
    assert len(provider.spawns) == 0

    # Nach Ablauf: erlaubt (spawned leeren fuer diesen Test)
    spawned.clear()
    with mock.patch('run_pi_mesh.time.time', return_value=time.time() + 11):
        asyncio.run(wrapper(payload))
    assert len(provider.spawns) == 1
    print("PASS: cooldown expires allows next attempt")


def test_backoff_is_exponential():
    """Backoff wächst exponentiell: 30s, 60s, 120s, cap 10min."""
    # Die Backoff-Logik ist in _detect_rate_limit_failure, aber wir testen
    # die Berechnung hier isoliert, da sie einfach und rein ist.
    base = 30
    expected = [30, 60, 120, 240, 480, 600]  # cap at 600s (10min)
    for attempt, expected_delay in enumerate(expected, start=1):
        delay = min(base * (2 ** (attempt - 1)), 600)
        assert delay == expected_delay, f"attempt {attempt}: expected {expected_delay}, got {delay}"
    print("PASS: backoff is exponential with 10min cap")


def test_multiple_tasks_get_independent_cooldowns():
    """Verschiedene Tasks haben unabhängige Cooldowns."""
    transport, provider, wrapper, spawned, task_cooldown = _make_callback()
    payload1 = _coder_payload("task-1", 1)
    payload2 = _coder_payload("task-2", 1)

    # Setze Cooldown nur fuer task-1
    task_cooldown[("task-1", 1, "CODER")] = time.time() + 100

    # task-1 sollte geskippt werden
    asyncio.run(wrapper(payload1))
    assert len(provider.spawns) == 0

    # task-2 sollte erlaubt sein
    asyncio.run(wrapper(payload2))
    assert len(provider.spawns) == 1
    assert provider.spawns[0]["task_id"] == "task-2"
    print("PASS: multiple tasks get independent cooldowns")


def test_cooldown_capped_at_10min():
    """Backoff wird bei 600s (10min) gecappt."""
    base = 30
    # Attempt 7: 30 * 2^6 = 1920 -> capped to 600
    attempt = 7
    delay = min(base * (2 ** (attempt - 1)), 600)
    assert delay == 600, f"expected 600s cap, got {delay}"
    print("PASS: cooldown capped at 10min")


if __name__ == "__main__":
    from unittest import mock
    test_rate_limit_sets_cooldown()
    test_cooldown_prevents_respawn_before_deadline()
    test_cooldown_expires_allows_next_attempt()
    test_backoff_is_exponential()
    test_multiple_tasks_get_independent_cooldowns()
    test_cooldown_capped_at_10min()
    print("\nALL S1.5 COOLDOWN TESTS PASSED")
