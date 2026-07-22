"""Tests: Spawn-Semaphore „Lock bis Response“.

Zwei Tests, klar getrennt:

A) Unit-Test (schnell, deterministisch):
   - Monkeypatch run_in_executor: gibt nie-endendes asyncio.Future zurück (kein Thread)
   - Event wird MANUELL gesetzt
   - Beweis: _spawn_limited endet SOFORT, ohne proc.wait() abzuwarten

B) Integration-Light (ohne Threads, ohne receiver.run Loop):
   - Extrahiere Event-Setting aus receiver.run() in _signal_task_done()
   - Teste diese Methode direkt
   - Beweis: Receiver signalisiert Task-Done nach publish_response()
"""
import asyncio
import json
import os
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from engine.transport.pi_mesh_transport import PiMeshTransport, WORKER_RESPONSE_SUFFIX
from engine.providers.pi_provider import PiProvider
from run_pi_mesh import PiMeshReceiverLoop, make_pimesh_messenger_callback


class TestSpawnSemaphoreUnit(unittest.TestCase):
    """Test A: Unit-Test – _spawn_limited gibt Slot frei, sobald Event gesetzt wird."""

    def test_slot_released_when_done_event_set(self):
        tmpdir = tempfile.mkdtemp(prefix="firma_test_")
        crew_root = os.path.join(tmpdir, "crew")
        os.makedirs(crew_root)
        coding = os.path.join(crew_root, "coding-crew")
        os.makedirs(coding)
        os.makedirs(os.path.join(coding, ".pi", "messenger", "crew", "tasks"), exist_ok=True)

        task_id = "task-semaphore-1"
        run_id = "run-semaphore-test"
        state_revision = 0
        role = "CODER"

        # --- Task-Files schreiben (damit dispatch() nicht fehlschlägt) ---
        tasks_dir = os.path.join(coding, ".pi", "messenger", "crew", "tasks")
        with open(os.path.join(tasks_dir, f"{task_id}.md"), "w", encoding="utf-8") as f:
            f.write(f"# Task {task_id}\n")
        payload = {
            "id": task_id,
            "title": f"Task {task_id}",
            "status": "todo",
            "firma_assignment": {
                "run_id": run_id,
                "task_id": task_id,
                "state_revision": state_revision,
                "role": role,
                "prompt": "do something",
            },
        }
        with open(os.path.join(tasks_dir, f"{task_id}.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f)

        transport = PiMeshTransport(
            crew_cwds={"CODER": "coding-crew"},
            project_root=crew_root,
        )
        provider = PiProvider()

        # --- Mock: Popen + proc.wait() blockiert FÜR IMMER ---
        never_ending_proc = MagicMock()
        never_ending_proc.pid = 99999
        never_ending_proc.wait = lambda: None  # wird eh nicht aufgerufen

        with patch("subprocess.Popen", return_value=never_ending_proc):
            callback, spawned, task_done_events = make_pimesh_messenger_callback(
                transport=transport,
                provider=provider,
                crew_cwds={"CODER": "coding-crew"},
                project_root=crew_root,
                models={"CODER": None},
            )

            receiver = PiMeshReceiverLoop(
                transport=transport,
                crew_cwds={"CODER": "coding-crew"},
                project_root=crew_root,
                expected_run_id=run_id,
                task_done_events=task_done_events,
            )

            spawn_payload = {
                "task_id": task_id,
                "run_id": run_id,
                "state_revision": state_revision,
                "role": role,
                "prompt": "do something",
                "task_definition": {},
            }

            async def run_test():
                # 1) Monkeypatch VOR dem Starten des Tasks:
                #    run_in_executor gibt nie-endendes Future zurück (kein Thread).
                loop = asyncio.get_event_loop()
                original_run_in_executor = loop.run_in_executor
                def mock_run_in_executor(executor, fn, *args):
                    return asyncio.Future()  # never completes

                loop.run_in_executor = mock_run_in_executor
                try:
                    # 2) Spawn starten (läuft im Hintergrund)
                    spawn_task = asyncio.create_task(callback(spawn_payload))
                    await asyncio.sleep(0.05)  # kurzer Yield, damit _spawn_limited beginnt

                    # 3) SIMULIERE receiver.run(): setze task_done_event MANUELL
                    wp = spawn_payload
                    key = (wp["task_id"], wp["state_revision"], wp["role"])
                    ev = task_done_events.get(key)
                    assert ev is not None, f"task_done_event fehlt für key={key}"
                    assert not ev.is_set(), "Event darf noch nicht gesetzt sein"
                    ev.set()

                    # 4) _spawn_limited MUSS jetzt SOFORT enden (proc_fut blockiert ja!)
                    t0 = time.time()
                    await asyncio.wait_for(spawn_task, timeout=1.0)
                    elapsed = time.time() - t0
                    self.assertLess(elapsed, 0.5, f"_spawn_limited hat zu spät geendet ({elapsed:.2f}s)")
                    self.assertTrue(ev.is_set())
                finally:
                    loop.run_in_executor = original_run_in_executor

            try:
                asyncio.run(run_test())
            finally:
                import shutil
                shutil.rmtree(tmpdir, ignore_errors=True)


class TestSpawnSemaphoreReceiverIntegration(unittest.TestCase):
    """Test B: Integration-Light – Receiver signalisiert Task-Done nach publish."""

    def test_signal_task_done_sets_event(self):
        tmpdir = tempfile.mkdtemp(prefix="firma_test_")
        crew_root = os.path.join(tmpdir, "crew")
        os.makedirs(crew_root)
        coding = os.path.join(crew_root, "coding-crew")
        os.makedirs(coding)
        os.makedirs(os.path.join(coding, ".pi", "messenger", "crew", "tasks"), exist_ok=True)

        task_id = "task-semaphore-signal"
        run_id = "run-semaphore-signal"
        state_revision = 0
        role = "CODER"

        transport = PiMeshTransport(
            crew_cwds={"CODER": "coding-crew"},
            project_root=crew_root,
        )
        receiver = PiMeshReceiverLoop(
            transport=transport,
            crew_cwds={"CODER": "coding-crew"},
            project_root=crew_root,
            expected_run_id=run_id,
        )

        # Simuliere _spawn_limited: Event registrieren
        key = (task_id, state_revision, role)
        ev = asyncio.Event()
        receiver.task_done_events[key] = ev

        # Payload wie nach publish_response()
        payload = {
            "task_id": task_id,
            "run_id": run_id,
            "state_revision": state_revision,
            "sender_role": role,
            "event": "CODE_SUBMITTED",
        }

        # BEFORE: Event nicht gesetzt
        self.assertFalse(ev.is_set())

        # ACT: Rufe die extrahierte Methode direkt auf
        receiver._signal_task_done(payload)

        # ASSERT: Event ist jetzt gesetzt
        self.assertTrue(ev.is_set(), "Event sollte nach _signal_task_done() gesetzt sein")

        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
