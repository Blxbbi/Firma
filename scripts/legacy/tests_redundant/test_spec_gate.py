import json
from engine.services.spec_gate import SpecGate

def test_spec_gate():
    # 1. Valid Plan
    valid_plan = {
        "version": "1.0",
        "project_id": "proj_123",
        "tasks": [
            {
                "id": "T1",
                "description": "Init project",
                "role": "CODER",
                "dependencies": [],
                "acceptance_criteria": [
                    {"type": "command", "value": "ls -la"}
                ]
            },
            {
                "id": "T2",
                "description": "Build app",
                "role": "CODER",
                "dependencies": ["T1"],
                "acceptance_criteria": [
                    {"type": "exists", "value": "app.py"}
                ]
            }
        ]
    }
    
    print("Testing Valid Plan...")
    res = SpecGate.validate(json.dumps(valid_plan))
    assert res.approved == True
    print("Valid Plan approved")

    # 2. Invalid JSON
    print("\nTesting Invalid JSON...")
    res = SpecGate.validate("{ invalid json }")
    assert res.approved == False
    print(f"Invalid JSON rejected: {res.errors}")

    # 3. Missing Field (Structural)
    invalid_struct = {
        "version": "1.0",
        "tasks": [] # missing project_id
    }
    print("\nTesting Missing Field...")
    res = SpecGate.validate(json.dumps(invalid_struct))
    assert res.approved == False
    print(f"Missing field rejected: {res.errors}")

    # 4. Invalid Role (Semantic)
    invalid_role = {
        "version": "1.0",
        "project_id": "proj_123",
        "tasks": [
            {
                "id": "T1",
                "description": "Init",
                "role": "MAGICIAN", # Invalid role
                "dependencies": [],
                "acceptance_criteria": [{"type": "command", "value": "ls"}]
            }
        ]
    }
    print("\nTesting Invalid Role...")
    res = SpecGate.validate(json.dumps(invalid_role))
    assert res.approved == False
    print(f"Invalid role rejected: {res.errors}")

    # 5. Cyclic Dependency (Semantic)
    cyclic_plan = {
        "version": "1.0",
        "project_id": "proj_123",
        "tasks": [
            {
                "id": "T1",
                "description": "T1",
                "role": "CODER",
                "dependencies": ["T2"],
                "acceptance_criteria": [{"type": "command", "value": "ls"}]
            },
            {
                "id": "T2",
                "description": "T2",
                "role": "CODER",
                "dependencies": ["T1"],
                "acceptance_criteria": [{"type": "command", "value": "ls"}]
            }
        ]
    }
    print("\nTesting Cyclic Dependencies...")
    res = SpecGate.validate(json.dumps(cyclic_plan))
    assert res.approved == False
    print(f"Cyclic dependency rejected: {res.errors}")

    # 6. Missing Dependency (Semantic)
    missing_dep = {
        "version": "1.0",
        "project_id": "proj_123",
        "tasks": [
            {
                "id": "T1",
                "description": "T1",
                "role": "CODER",
                "dependencies": ["T99"], # Non-existent
                "acceptance_criteria": [{"type": "command", "value": "ls"}]
            }
        ]
    }
    print("\nTesting Missing Dependency...")
    res = SpecGate.validate(json.dumps(missing_dep))
    assert res.approved == False
    print(f"Missing dependency rejected: {res.errors}")

if __name__ == "__main__":
    test_spec_gate()
    print("\nAll Spec-Gate tests passed!")
