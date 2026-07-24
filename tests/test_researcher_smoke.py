"""
Smoke test for the Researcher worker.

Run via: python tests/test_researcher_smoke.py

Covers:
  - ResearcherWorker in dummy mode returns a valid Message
  - ResearcherWorker produces a research/brief.md artifact
  - ResearcherWorker output contains expected sections (Findings, Recommendations, Risks)
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workers.researcher import ResearcherWorker
from engine.providers.base import BaseLLMProvider
from engine.models import TaskEvent


class _MockResearcherProvider(BaseLLMProvider):
    def __init__(self):
        self.model_name = "mock/researcher-smoke"

    async def _generate(self, system_prompt: str, user_prompt: str, timeout: int) -> str:
        return "mock"

    async def _generate_json(self, system_prompt: str, user_prompt: str, schema, timeout: int):
        return {
            "brief_markdown": (
                "# Research Brief\n\n"
                "## Project Findings\n"
                "- file: README.md | line: 1 | evidence: Firma\n\n"
                "## Recommendations for Planner\n"
                "- Create index.html, style.css, app.js\n\n"
                "## Risks/Constraints\n"
                "- No existing web project found\n"
            )
        }


def test_researcher_dummy_mode():
    provider = _MockResearcherProvider()
    worker = ResearcherWorker(provider=provider, model_name="mock/model", dummy_mode=True)

    response = asyncio.run(
        worker.handle_request(
            project_id="test-project",
            user_prompt="Erstelle eine moderne Website fuer ein KI-Startup.",
            task_id="task-researcher-1",
            run_id="run-123",
            project_root=str(Path(__file__).resolve().parent.parent),
        )
    )

    assert response.header.sender == "researcher-worker"
    assert response.header.recipient == "engine"
    assert response.payload["sender_role"] == "RESEARCHER"
    assert response.payload["event"] == TaskEvent.RESEARCH_COMPLETE.value
    assert response.payload["task_id"] == "task-researcher-1"
    assert response.payload["run_id"] == "run-123"

    artifacts = response.payload.get("artifacts", [])
    assert len(artifacts) == 1
    art = artifacts[0]
    assert art["path"] == "research/brief.md"
    assert art["action"] == "CREATE"
    content = art["content"]

    # Verify the user prompt is represented as the primary input
    assert "Erstelle eine moderne Website fuer ein KI-Startup" in content

    # Verify expected sections
    assert "# Research Brief" in content
    assert "## Project Findings" in content
    assert "## Recommendations for Planner" in content
    assert "## Risks/Constraints" in content

    # Verify citations are present
    assert "file:" in content
    assert "line:" in content
    assert "evidence:" in content

    print("PASS test_researcher_dummy_mode")
    print(f"  - event: {response.payload['event']}")
    print(f"  - artifacts: {[a['path'] for a in artifacts]}")
    print(f"  - brief length: {len(content)} chars")
    print(f"  - preview:\n{content[:300]}...")


if __name__ == "__main__":
    test_researcher_dummy_mode()
    print("\nOK")

