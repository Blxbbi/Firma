import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# run_pi_mesh hat schwere Top-Level-Imports (engine.models, engine.settings, ...).
# Für diese Unit-Tests mocken wir die problematischen Module vor dem Import,
# sodass nur die zu testenden Helfer geladen werden.
# ---------------------------------------------------------------------------
_models_mock = MagicMock()
_settings_mock = MagicMock()
_settings_mock.ARTIFACT_DIR = "/tmp/firma-artifacts"

sys.modules.setdefault("engine.models", _models_mock)
sys.modules.setdefault("engine.settings", _settings_mock)

import run_pi_mesh as rpm  # noqa: E402


# Fallback: falls spätere Imports weitere Module brauchen, mocking nachziehen.
def _ensure_mock(module_name):
    if module_name not in sys.modules or not getattr(sys.modules[module_name], "__mocked", False):
        m = MagicMock()
        m.__mocked = True
        sys.modules.setdefault(module_name, m)

for _mod in [
    "engine.services.verification_registry",
    "engine.services.verifiers.web_verifier",
    "engine.services.workspace_materializer",
    "engine.providers.pi_provider",
    "engine.transport.base",
    "engine.transport.internal_transport",
    "engine.transport.pimessenger",
    "engine.session_registry",
    "engine.repository",
    "engine.services.execution",
    "engine.services.run_archive",
    "engine.services.ingest_context",
    "engine.services.guardian",
]:
    _ensure_mock(_mod)


def test_review_target_paths_from_strings():
    payload = {
        "task_definition": {
            "expected_artifacts": ["index.html", "style.css", "game.js"],
        }
    }
    paths = rpm._review_target_paths(payload)
    assert paths == ["game.js", "index.html", "style.css"]


def test_review_target_paths_from_dicts():
    payload = {
        "task_definition": {
            "expected_artifacts": [
                {"path": "src/app.js", "type": "CREATE"},
                {"path": "src/style.css", "type": "CREATE"},
            ],
        }
    }
    paths = rpm._review_target_paths(payload)
    assert paths == ["src/app.js", "src/style.css"]


def test_review_target_paths_mixed_and_deduped():
    payload = {
        "expected_artifacts": ["index.html", {"path": "index.html"}],
        "task_definition": {},
    }
    paths = rpm._review_target_paths(payload)
    assert paths == ["index.html"]


def test_review_target_paths_fallback_empty_when_nothing_provided():
    payload = {"task_definition": {}}
    paths = rpm._review_target_paths(payload)
    assert paths == []


def test_review_target_paths_rejects_traversal(monkeypatch, tmp_path):
    payload = {
        "task_definition": {
            "expected_artifacts": ["../secrets.txt", "/etc/passwd"],
        }
    }
    monkeypatch.setattr(rpm, "ARTIFACT_DIR", str(tmp_path))
    out = rpm._load_artifacts_for_review("run-x", "task-1", payload)
    assert out == {}


def test_review_loads_only_expected_artifacts(monkeypatch, tmp_path):
    base = tmp_path / "run-x" / "task-1"
    base.mkdir(parents=True)
    (base / "index.html").write_text("<html></html>", encoding="utf-8")
    (base / "style.css").write_text("body{}", encoding="utf-8")
    (base / "game.js").write_text("console.log(1)", encoding="utf-8")

    payload = {
        "task_definition": {
            "expected_artifacts": ["index.html"],
        }
    }
    monkeypatch.setattr(rpm, "ARTIFACT_DIR", str(tmp_path))

    out = rpm._load_artifacts_for_review("run-x", "task-1", payload)

    assert list(out.keys()) == ["index.html"]
    assert out["index.html"] == "<html></html>"


def test_review_does_not_load_all_when_expected_missing(monkeypatch, tmp_path):
    base = tmp_path / "run-x" / "task-1"
    base.mkdir(parents=True)
    (base / "index.html").write_text("<html></html>", encoding="utf-8")
    (base / "style.css").write_text("body{}", encoding="utf-8")

    payload = {"task_definition": {}}
    monkeypatch.setattr(rpm, "ARTIFACT_DIR", str(tmp_path))

    out = rpm._load_artifacts_for_review("run-x", "task-1", payload)

    # No expected_artifacts -> fallback: load all actual files present in the artifact dir
    assert set(out.keys()) == {"index.html", "style.css"}
    assert out["index.html"] == "<html></html>"
    assert out["style.css"] == "body{}"



def test_review_spec_has_one_pass_contract_and_no_global_goal():
    transport = __import__("engine.transport.pi_mesh_transport", fromlist=["PiMeshTransport"]).PiMeshTransport(
        crew_cwds={"REVIEWER": "reviewing-crew"},
        project_root="/fake/project",
    )
    payload = {
        "run_id": "run-1",
        "task_id": "task-1",
        "state_revision": 1,
        "prompt": "Create a snake game.",
        "role": "REVIEWER",
        "task_definition": {
            "description": "Review index.html.",
            "acceptance_criteria": ["index.html exists", "index.html contains <canvas>"],
            "expected_artifacts": ["index.html"],
        },
    }
    md = transport._build_spec_markdown(payload, review_artifacts={"index.html": "<canvas></canvas>"})

    assert "ONE PASS" in md
    assert "Do NOT edit files" in md
    assert "REVIEW_APPROVED" in md
    assert "REVIEW_FAILURE" in md
    assert "Global Goal (BACKGROUND ONLY)" not in md


def test_reviewer_persona_allows_only_read_write():
    import pathlib

    persona_path = pathlib.Path("pimesh/reviewing-crew/.pi/messenger/crew/agents/crew-worker.md")
    text = persona_path.read_text(encoding="utf-8")

    assert text.count("tools:") >= 1
    assert "tools: read, write" in text.lower()
    assert "edit" not in text.lower().split("tools:")[1].split("\n")[0]
    assert "bash" not in text.lower().split("tools:")[1].split("\n")[0]
