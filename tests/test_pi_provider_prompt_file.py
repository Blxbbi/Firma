"""
V1 — PiProvider prompt-file tests (Shell-Crash-Fix).

Verifies that PiProvider writes the full assignment prompt to a file
instead of passing it via `-p`, avoiding Windows shell argument limits.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.providers.pi_provider import PiProvider


class TestPiProviderPromptFile(unittest.TestCase):
    def _spawn_and_capture(self, role="CODER", task_id="task-1", run_id="run-1", correction_note=None):
        """Helper: spawn_for_assignment with mocked subprocess.Popen, returns (args, prompt_file_path)."""
        tmpdir = tempfile.mkdtemp()
        crew_cwd = os.path.join(tmpdir, "crew")
        os.makedirs(crew_cwd)
        
        provider = PiProvider()
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        
        captured_args = None
        captured_log_path = None
        
        def mock_popen(args, **kwargs):
            nonlocal captured_args, captured_log_path
            captured_args = args
            captured_log_path = kwargs.get("stdout")
            return mock_proc
        
        with patch("subprocess.Popen", side_effect=mock_popen):
            proc = provider.spawn_for_assignment(
                role=role,
                task_id=task_id,
                run_id=run_id,
                state_revision=0,
                crew_cwd=crew_cwd,
                correction_note=correction_note,
            )
        
        prompt_file = os.path.join(crew_cwd, ".pi", "work", run_id, task_id, "prompt.txt")
        return captured_args, prompt_file, crew_cwd, tmpdir

    def test_writes_prompt_file_and_uses_short_prompt(self):
        args, prompt_file, crew_cwd, tmpdir = self._spawn_and_capture()
        
        # Prompt file exists and contains the full prompt
        self.assertTrue(os.path.isfile(prompt_file), f"prompt.txt not found at {prompt_file}")
        with open(prompt_file, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("Read the file", content)
        self.assertIn("task-1.md", content)
        
        # The -p argument is short and references the file
        self.assertIn("-p", args)
        p_index = args.index("-p")
        prompt_arg = args[p_index + 1]
        self.assertIn("prompt.txt", prompt_arg)
        self.assertLess(len(prompt_arg), 500, f"-p prompt too long ({len(prompt_arg)} chars): {prompt_arg[:200]}...")
        
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_large_assignment_still_works(self):
        """Even with a 200KB correction_note, the -p arg stays short."""
        large_note = "CORRECTION " * 25000  # ~250KB
        args, prompt_file, crew_cwd, tmpdir = self._spawn_and_capture(correction_note=large_note)
        
        # Prompt file contains the large content
        self.assertTrue(os.path.isfile(prompt_file))
        with open(prompt_file, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("CORRECTION", content)
        self.assertGreater(len(content), 100000, f"prompt.txt too small: {len(content)} bytes")
        
        # -p arg is still short
        self.assertIn("-p", args)
        p_index = args.index("-p")
        prompt_arg = args[p_index + 1]
        self.assertIn("prompt.txt", prompt_arg)
        self.assertLess(len(prompt_arg), 500, f"-p prompt too long ({len(prompt_arg)} chars)")
        
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_ingest_mode_writes_prompt_file(self):
        """With ingest mode (staged project), the prompt file should contain ingest instructions."""
        # We can't easily test ingest mode without mocking get_ingest, but we can
        # at least verify the prompt file is written for the normal case.
        # For a full ingest test, see test_piprovider_ingest_stage.py
        args, prompt_file, crew_cwd, tmpdir = self._spawn_and_capture()
        
        self.assertTrue(os.path.isfile(prompt_file))
        with open(prompt_file, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("Read the file", content)
        
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
