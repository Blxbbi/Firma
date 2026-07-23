"""
Tests for role/mode-based tool policy in PiProvider.
"""
from __future__ import annotations

import pytest

from engine.providers.pi_provider import PiProvider


@pytest.mark.parametrize(
    "role,expected",
    [
        ("REVIEWER", "read,write"),
        ("PLANNER", "read,write"),
        ("RESEARCHER", "read,write"),
        ("CODER", "read,write,edit"),
        ("SYSTEM", "read,write,edit,bash"),
    ],
)
def test_tools_for_role_default(role, expected):
    assert PiProvider.tools_for_role(role) == expected


@pytest.mark.parametrize(
    "role,mode,expected",
    [
        ("CODER", "from-scratch", "read,write,edit"),
        ("CODER", "ingest", "read,write,edit"),
        ("CODER", "edit", "read,write,edit"),
        ("REVIEWER", "from-scratch", "read,write"),
        ("PLANNER", "ingest", "read,write"),
    ],
)
def test_tools_for_role_with_mode(role, mode, expected):
    assert PiProvider.tools_for_role(role, mode=mode) == expected


def test_spawn_for_assignment_uses_role_tools(monkeypatch, tmp_path):
    captured = {}

    class DummyProvider:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            captured.setdefault('init', []).append(kwargs)

        @staticmethod
        def tools_for_role(role, mode=None):
            return "read,write" if role == "REVIEWER" else "read,write,edit"

        def _stage_ingest_project_if_needed(self, role, run_id, task_id, crew_cwd):
            return None

        def build_assignment_prompt(self, task_id, correction_note=None):
            return "prompt"

        def spawn_worker(self, crew_cwd, prompt, **kwargs):
            captured.setdefault('spawn', []).append(kwargs)
            return None

    monkeypatch.setattr("engine.providers.pi_provider.PiProvider", DummyProvider)

    provider = PiProvider()
    provider.spawn_for_assignment(
        role="REVIEWER",
        task_id="task-1",
        run_id="run-1",
        state_revision=1,
        crew_cwd=str(tmp_path),
    )
    assert captured['spawn'][-1]['provider'] is None
    assert captured['spawn'][-1]['model'] is None
    assert captured['init'][-1]['tools'] == "read,write"
