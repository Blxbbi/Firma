from engine.schemas.llm import LLMResponse, ArtifactChange, FileAction
from pydantic import ValidationError

def run_test(name, func):
    try:
        func()
        print(f"[OK] {name}")
    except Exception as e:
        print(f"[FAIL] {name}")
        print(f"   Error: {e}")

def test_valid_create():
    resp = LLMResponse(artifacts=[{"path": "main.py", "content": "print('hi')", "action": "CREATE"}])
    assert resp.artifacts[0].path == "main.py"

def test_valid_delete():
    resp = LLMResponse(artifacts=[{"path": "old.txt", "action": "DELETE"}])
    assert resp.artifacts[0].action == FileAction.DELETE

def test_invalid_path_traversal():
    try:
        LLMResponse(artifacts=[{"path": "../secret.txt", "content": "x", "action": "CREATE"}])
        raise Exception("Should have failed!")
    except ValidationError:
        pass

def test_invalid_content_on_create():
    try:
        LLMResponse(artifacts=[{"path": "new.py", "action": "CREATE"}])
        raise Exception("Should have failed!")
    except ValidationError:
        pass

def test_invalid_content_on_delete():
    try:
        LLMResponse(artifacts=[{"path": "old.txt", "content": "x", "action": "DELETE"}])
        raise Exception("Should have failed!")
    except ValidationError:
        pass

if __name__ == "__main__":
    print("--- Starting Schema Verification ---")
    run_test("Valid Create", test_valid_create)
    run_test("Valid Delete", test_valid_delete)
    run_test("Path Traversal Detection", test_invalid_path_traversal)
    run_test("Missing Content on Create", test_invalid_content_on_create)
    run_test("Content on Delete", test_invalid_content_on_delete)
    print("--- Verification Complete ---")
