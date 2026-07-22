"""
Optional/slow integration test: verifies that the real `pi` runtime reads
prompt.txt and executes it correctly.

Current status: SKIPPED by default.
Reason: With `--extension pi-messenger`, `pi` prioritizes its crew-task logic over the
inline `-p` prompt. A successful run requires either:
  - a dedicated crew-task harness (Option A, separate test category), or
  - starting `pi` without `pi-messenger` extension.

Manual opt-in (current file-based prompt path, not crew-task harness):
  FIRMA_RUN_PI_INTEGRATION=1 FIRMA_PI_INTEGRATION_MODE=direct_prompt pytest tests/test_pi_provider_prompt_file_integration.py

Future crew-task harness test should:
  - create `.pi/messenger/crew/tasks/task-integration.md/.json`
  - reference `.pi/work/.../prompt.txt` inside the task spec
  - assert `output_marker.txt` + `worker_response` exist
"""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.providers.pi_provider import PiProvider

# Gate: skip unless explicitly requested.
RUN_INTEGRATION = os.environ.get("FIRMA_RUN_PI_INTEGRATION") == "1"
# Keep future crew-task harness in a separate mode so this test stays focused on the
# current V1 fix (prompt via file, no pi-messenger crew-task harness).
INTEGRATION_MODE = os.environ.get("FIRMA_PI_INTEGRATION_MODE", "")

MAGIC_TOKEN = "MAGIC_TOKEN_41C6C739"


class TestPiProviderPromptFileIntegration(unittest.TestCase):
    @unittest.skipUnless(
        RUN_INTEGRATION and INTEGRATION_MODE == "direct_prompt",
        "Skip default: pi-messenger extension ignores `-p` prompt in favor of crew-task logic. "
        "Requires FIRMA_RUN_PI_INTEGRATION=1 and FIRMA_PI_INTEGRATION_MODE=direct_prompt. "
        "A realistic crew-task harness test (Option A) is planned separately.",
    )
    def test_pi_reads_prompt_file_and_writes_output(self):
        tmpdir = tempfile.mkdtemp(prefix="firma_pi_integration_")
        crew_cwd = os.path.join(tmpdir, "crew")
        os.makedirs(crew_cwd)

        run_id = "run-integration"
        task_id = "task-integration"

        # Build a small, deterministic prompt that guarantees success.
        prompt_text = (
            "You are a worker agent. Write a file named `output_marker.txt` in the current working directory "
            f"containing EXACTLY: {MAGIC_TOKEN}\nThen stop."
        )

        prompt_file = os.path.join(crew_cwd, ".pi", "work", run_id, task_id, "prompt.txt")
        os.makedirs(os.path.dirname(prompt_file), exist_ok=True)
        with open(prompt_file, "w", encoding="utf-8") as f:
            f.write(prompt_text)

        provider = PiProvider()
        try:
            proc = provider.spawn_for_assignment(
                role="CODER",
                task_id=task_id,
                run_id=run_id,
                state_revision=0,
                crew_cwd=crew_cwd,
            )
        except FileNotFoundError:
            self.skipTest("pi executable not found on PATH")

        self.assertIsNotNone(proc)
        self.assertEqual(proc.returncode, None)

        marker_path = os.path.join(crew_cwd, "output_marker.txt")
        deadline = time.time() + 120
        while time.time() < deadline:
            if os.path.isfile(marker_path):
                break
            time.sleep(0.5)
        else:
            self.fail("pi did not create output_marker.txt within timeout")

        with open(marker_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        self.assertEqual(content, MAGIC_TOKEN)

        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
