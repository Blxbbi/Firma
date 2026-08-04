"""
Tests for Greenfield Scope Enforcement (P1) in GuardianPipeline.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from engine.models import Task, TaskEvent, FileAction
from engine.services.guardian import GuardianPipeline


def _make_task(expected_artifacts):
    task = MagicMock(spec=Task)
    task.id = "task-1"
    task.expected_artifacts = expected_artifacts
    return task


def _make_response(artifacts):
    response = MagicMock()
    response.artifacts = artifacts
    return response


class TestValidateCoderScope:
    def setup_method(self):
        self.pipeline = GuardianPipeline(artifact_store=MagicMock())

    def test_accepts_exact_expected_artifacts(self):
        task = _make_task([{"path": "style.css", "type": "CREATE"}])
        response = _make_response([
            {"path": "style.css", "action": FileAction.CREATE.value, "content": "body{}"}
        ])
        ok, err = self.pipeline._validate_coder_scope(task, response)
        assert ok is True
        assert err is None

    def test_rejects_out_of_scope_artifacts(self):
        task = _make_task([{"path": "style.css", "type": "CREATE"}])
        response = _make_response([
            {"path": "style.css", "action": FileAction.CREATE.value, "content": "body{}"},
            {"path": "index.html", "action": FileAction.CREATE.value, "content": "<html></html>"},
        ])
        ok, err = self.pipeline._validate_coder_scope(task, response)
        assert ok is False
        assert "OUT_OF_SCOPE_ARTIFACTS" in err
        assert "index.html" in err

    def test_accepts_empty_expected_when_no_artifacts_submitted(self):
        task = _make_task([])
        response = _make_response([])
        ok, err = self.pipeline._validate_coder_scope(task, response)
        assert ok is True
        assert err is None

    def test_allows_update_action_in_scope(self):
        task = _make_task([{"path": "app.js", "type": "UPDATE"}])
        response = _make_response([
            {"path": "app.js", "action": FileAction.UPDATE.value, "content": "console.log('hi');"}
        ])
        ok, err = self.pipeline._validate_coder_scope(task, response)
        assert ok is True
        assert err is None

    def test_rejects_update_out_of_scope(self):
        task = _make_task([{"path": "app.js", "type": "UPDATE"}])
        response = _make_response([
            {"path": "app.js", "action": FileAction.UPDATE.value, "content": "x"},
            {"path": "utils.js", "action": FileAction.UPDATE.value, "content": "y"},
        ])
        ok, err = self.pipeline._validate_coder_scope(task, response)
        assert ok is False
        assert "utils.js" in err

    def test_ignores_delete_actions_for_scope_check(self):
        task = _make_task([{"path": "old.css", "type": "CREATE"}])
        response = _make_response([
            {"path": "old.css", "action": FileAction.DELETE.value},
        ])
        ok, err = self.pipeline._validate_coder_scope(task, response)
        assert ok is True
        assert err is None

    def test_normalizes_backslashes_in_paths(self):
        task = _make_task([{"path": "src/index.html", "type": "CREATE"}])
        response = _make_response([
            {"path": "src\\index.html", "action": FileAction.CREATE.value, "content": "<html></html>"},
        ])
        ok, err = self.pipeline._validate_coder_scope(task, response)
        assert ok is True
        assert err is None

    def test_message_contains_both_out_of_scope_and_expected(self):
        task = _make_task([{"path": "style.css", "type": "CREATE"}])
        response = _make_response([
            {"path": "index.html", "action": FileAction.CREATE.value, "content": "<html></html>"},
        ])
        ok, err = self.pipeline._validate_coder_scope(task, response)
        assert ok is False
        assert "index.html" in err
        assert "style.css" in err
