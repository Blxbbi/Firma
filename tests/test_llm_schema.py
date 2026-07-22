import pytest
from engine.schemas.llm import LLMResponse, ArtifactChange, FileAction
from pydantic import ValidationError

def test_valid_create():
    data = {
        "artifacts": [
            {"path": "main.py", "content": "print('hi')", "action": "CREATE"}
        ]
    }
    resp = LLMResponse(**data)
    assert len(resp.artifacts) == 1
    assert resp.artifacts[0].path == "main.py"

def test_valid_update():
    data = {
        "artifacts": [
            {"path": "config.json", "content": '{"a": 1}', "action": "UPDATE"}
        ]
    }
    resp = LLMResponse(**data)
    assert resp.artifacts[0].action == FileAction.UPDATE

def test_valid_delete():
    data = {
        "artifacts": [
            {"path": "old_file.txt", "action": "DELETE"}
        ]
    }
    resp = LLMResponse(**data)
    assert resp.artifacts[0].action == FileAction.DELETE
    assert resp.artifacts[0].content is None

def test_invalid_path_traversal():
    with pytest.raises(ValidationError) as excinfo:
        LLMResponse(artifacts=[{"path": "../secret.txt", "content": "x", "action": "CREATE"}])
    assert "Invalid path" in str(excinfo.value)

    with pytest.raises(ValidationError) as excinfo:
        LLMResponse(artifacts=[{"path": "/etc/passwd", "content": "x", "action": "CREATE"}])
    assert "Invalid path" in str(excinfo.value)

def test_invalid_content_on_create():
    with pytest.raises(ValidationError) as excinfo:
        LLMResponse(artifacts=[{"path": "new.py", "action": "CREATE"}])
    assert "Content is required" in str(excinfo.value)

def test_invalid_content_on_delete():
    with pytest.raises(ValidationError) as excinfo:
        LLMResponse(artifacts=[{"path": "old.txt", "content": "should not be here", "action": "DELETE"}])
    assert "DELETE action must not contain content" in str(excinfo.value)

def test_empty_artifacts():
    resp = LLMResponse(artifacts=[])
    assert len(resp.artifacts) == 0

if __name__ == "__main__":
    import sys
    # Simple manual runner if pytest is not installed
    try:
        import pytest
        pytest.main([__file__])
    except ImportError:
        print("Pytest not found, running manual checks...")
        # (simplified manual checks)
        print("Manual checks require implementation. Please install pytest.")
        sys.exit(1)
