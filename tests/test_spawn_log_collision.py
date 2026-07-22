"""Integrationstest: Zwei Spawns back-to-back duerfen sich nicht gegenseitig
ueberschreiben (pro-Task worker.log + worker_response).

Strategie: Mock subprocess.Popen so, dass der gemockte Prozess sofort eine
minimale worker_response-Datei + Log-Eintrag schreibt. Dann spawnen wir zwei
Assignments und verifizieren:
- Jede Task hat ihren eigenen worker.log
- Jede Task hat ihre eigene worker_response-Datei
- Receiver scan_once() findet BEIDE Responses
"""
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from engine.transport.pi_mesh_transport import PiMeshTransport, WORKER_RESPONSE_SUFFIX
from engine.providers.pi_provider import PiProvider
from run_pi_mesh import PiMeshReceiverLoop


class TestSpawnLogCollision(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="firma_test_")
        self.crew_root = os.path.join(self.tmpdir, "crew")
        os.makedirs(self.crew_root)
        self.planning = os.path.join(self.crew_root, "planning-crew")
        self.coding = os.path.join(self.crew_root, "coding-crew")
        os.makedirs(self.planning)
        os.makedirs(self.coding)
        for d in (self.planning, self.coding):
            os.makedirs(os.path.join(d, ".pi", "messenger", "crew"), exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_task_files(self, crew_cwd, task_id, role, run_id, state_revision=0):
        tasks_dir = os.path.join(crew_cwd, ".pi", "messenger", "crew", "tasks")
        os.makedirs(tasks_dir, exist_ok=True)
        with open(os.path.join(tasks_dir, f"{task_id}.md"), "w", encoding="utf-8") as f:
            f.write(f"# Task {task_id}\n\nrole={role}\nrun_id={run_id}\n")
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

    def _make_mock_popen(self, crew_cwd, run_id, task_id):
        """Erzeugt eine Popen-Klasse, die sofort response + log schreibt."""
        worker_dir = os.path.join(crew_cwd, ".pi", "messenger", "crew")
        resp_file = os.path.join(worker_dir, f"worker_response.{task_id}{WORKER_RESPONSE_SUFFIX}")
        log_path = os.path.join(crew_cwd, ".pi", "work", run_id, task_id, "worker.log")

        def _init(*args, **kwargs):
            # response schreiben
            response = {
                "protocol_version": "1.0",
                "message_id": f"{task_id}-mock-1",
                "task_id": task_id,
                "run_id": run_id,
                "state_revision": 0,
                "event": "CODE_SUBMITTED",
                "sender_role": "CODER",
                "artifacts": [{"path": "style.css", "action": "CREATE", "content": "body{color:red}"}],
                "timestamp": "2026-07-21T08:58:00Z",
                "logs": "mock worker",
            }
            os.makedirs(os.path.dirname(resp_file), exist_ok=True)
            with open(resp_file, "w", encoding="utf-8") as f:
                json.dump(response, f)

            # artifact schreiben
            os.makedirs(worker_dir, exist_ok=True)
            with open(os.path.join(worker_dir, "style.css"), "w", encoding="utf-8") as f:
                f.write("body{color:red}")

            # eigenes Log schreiben
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(f"MOCK WORKER LOG for task_id={task_id}\n")

            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_proc.returncode = 0
            mock_proc.wait = MagicMock(return_value=None)
            return mock_proc

        return _init

    def test_two_spawns_no_collision(self):
        run_id = "run-collision-test"
        task1 = "task-collision-1"
        task2 = "task-collision-2"

        self._write_task_files(self.coding, task1, "CODER", run_id)
        self._write_task_files(self.coding, task2, "CODER", run_id)

        transport = PiMeshTransport(
            crew_cwds={"PLANNER": "planning-crew", "CODER": "coding-crew", "REVIEWER": "reviewing-crew"},
            project_root=self.crew_root,
        )
        provider = PiProvider()

        mock_popen_1 = self._make_mock_popen(self.coding, run_id, task1)
        mock_popen_2 = self._make_mock_popen(self.coding, run_id, task2)

        with patch("subprocess.Popen") as mock_popen:
            mock_popen.side_effect = [mock_popen_1(), mock_popen_2()]
            provider.spawn_for_assignment(
                role="CODER", task_id=task1, run_id=run_id, state_revision=0,
                crew_cwd=self.coding, model=None, session_id=None, session_dir=None,
            )
            provider.spawn_for_assignment(
                role="CODER", task_id=task2, run_id=run_id, state_revision=0,
                crew_cwd=self.coding, model=None, session_id=None, session_dir=None,
            )

        # --- Assertions: pro-Task Logs existieren ---
        log1 = os.path.join(self.coding, ".pi", "work", run_id, task1, "worker.log")
        log2 = os.path.join(self.coding, ".pi", "work", run_id, task2, "worker.log")
        self.assertTrue(os.path.isfile(log1), f"worker.log fuer {task1} fehlt")
        self.assertTrue(os.path.isfile(log2), f"worker.log fuer {task2} fehlt")

        with open(log1, "r", encoding="utf-8") as f:
            self.assertIn(task1, f.read())
        with open(log2, "r", encoding="utf-8") as f:
            self.assertIn(task2, f.read())

        # --- Assertions: beide Responses existieren ---
        resp1 = os.path.join(self.coding, ".pi", "messenger", "crew", f"worker_response.{task1}{WORKER_RESPONSE_SUFFIX}")
        resp2 = os.path.join(self.coding, ".pi", "messenger", "crew", f"worker_response.{task2}{WORKER_RESPONSE_SUFFIX}")
        self.assertTrue(os.path.isfile(resp1), f"worker_response fuer {task1} fehlt")
        self.assertTrue(os.path.isfile(resp2), f"worker_response fuer {task2} fehlt")

        # --- Assertion: Receiver findet BEIDE ---
        receiver = PiMeshReceiverLoop(
            transport=transport,
            crew_cwds={"PLANNER": "planning-crew", "CODER": "coding-crew", "REVIEWER": "reviewing-crew"},
            project_root=self.crew_root,
            expected_run_id=run_id,
        )
        items = receiver.scan_once()
        task_ids_found = {it["correlation_id"] for it in items}
        self.assertIn(task1, task_ids_found, f"Receiver hat {task1} nicht gefunden")
        self.assertIn(task2, task_ids_found, f"Receiver hat {task2} nicht gefunden")
        self.assertEqual(len(items), 2, "Receiver soll genau 2 Responses liefern")


if __name__ == "__main__":
    unittest.main()
