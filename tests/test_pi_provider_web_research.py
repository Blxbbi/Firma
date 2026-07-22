"""
R2 Web Research (opt-in) — PiProvider prompt tests.

Verifies that the Researcher prompt includes web research rules only when
`FIRMA_RESEARCH_WEB=1`, and that the contract stays read-only + source-cited.
"""
import contextlib
import importlib
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _spawn_researcher(env_overrides=None, mock_workdir=None):
    """Helper: spawn_for_assignment for RESEARCHER with mocked Popen, returns prompt_file content.

    Forces ingest mode by stubbing `_stage_ingest_project_if_needed` when `mock_workdir` is given.
    Reloads settings + provider so module-level flags pick up the patched env.
    """
    tmpdir = tempfile.mkdtemp()
    crew_cwd = os.path.join(tmpdir, "crew")
    os.makedirs(crew_cwd)

    env = {**os.environ, **(env_overrides or {})}
    with patch.dict(os.environ, env, clear=False):
        import engine.settings as settings_mod
        importlib.reload(settings_mod)
        import engine.providers.pi_provider as provider_mod
        importlib.reload(provider_mod)

        provider = provider_mod.PiProvider()
        mock_proc = MagicMock()
        mock_proc.pid = 12345

        def mock_popen(args, **kwargs):
            return mock_proc

        patches = [patch("subprocess.Popen", side_effect=mock_popen)]
        if mock_workdir is not None:
            patches.append(
                patch.object(
                    provider,
                    "_stage_ingest_project_if_needed",
                    return_value=mock_workdir,
                )
            )
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            provider.spawn_for_assignment(
                role="RESEARCHER",
                task_id="task-1",
                run_id="run-1",
                state_revision=0,
                crew_cwd=crew_cwd,
            )

    prompt_file = os.path.join(crew_cwd, ".pi", "work", "run-1", "task-1", "prompt.txt")
    with open(prompt_file, "r", encoding="utf-8") as f:
        content = f.read()
    return content, tmpdir


class TestPiProviderWebResearchPrompt(unittest.TestCase):
    def test_researcher_prompt_without_web_research(self):
        """Default: web research is off; prompt must not mention web rules."""
        workdir = os.path.join(tempfile.gettempdir(), "firma_test_web_research_off", "crew", "project")
        content, tmpdir = _spawn_researcher({"FIRMA_RESEARCH_WEB": "0"}, mock_workdir=workdir)
        self.assertIn("research/brief.md", content)
        self.assertIn("STRICT READ-ONLY", content)
        self.assertNotIn("[Web Research]", content)
        self.assertNotIn("curl", content)
        self.assertNotIn("wget", content)
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_researcher_prompt_with_web_research(self):
        """When enabled, prompt must include web rules, query budget, timeout, and source URL rule."""
        workdir = os.path.join(tempfile.gettempdir(), "firma_test_web_research_on", "crew", "project")
        content, tmpdir = _spawn_researcher({
            "FIRMA_RESEARCH_WEB": "1",
            "FIRMA_RESEARCH_WEB_MAX_QUERIES": "5",
            "FIRMA_RESEARCH_WEB_TIMEOUT_S": "45",
        }, mock_workdir=workdir)
        self.assertIn("[Web Research]", content)
        self.assertIn("max 5 queries", content)
        self.assertIn("45s timeout", content)
        self.assertIn("curl", content)
        self.assertIn("wget", content)
        self.assertIn("source URL", content)
        self.assertIn("Web research unavailable: <reason>", content)
        self.assertIn("## External research (sources)", content)
        self.assertIn("non-compliance", content)
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_researcher_prompt_web_research_defaults(self):
        """When enabled without explicit limits, defaults must be injected."""
        workdir = os.path.join(tempfile.gettempdir(), "firma_test_web_research_defaults", "crew", "project")
        content, tmpdir = _spawn_researcher({"FIRMA_RESEARCH_WEB": "1"}, mock_workdir=workdir)
        self.assertIn("max 3 queries", content)
        self.assertIn("30s timeout", content)
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
