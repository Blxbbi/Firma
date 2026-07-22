"""
Phase 2 (Idee A) - Step3.1/3.2: TaskDefinition schema + scope/protected policy tests.

Run via: ./tools/safe_test.sh tests/test_phase2_spec_schema.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.models import TaskDefinition
from engine.services.scope_policy import compute_protected_files, apply_ingest_scope


# --- 3.1 schema ----------------------------------------------------------------
def test_task_definition_defaults():
    # backward compat: a plain CODER task with no scope fields is valid
    td = TaskDefinition(
        id="task-1",
        description="Implement index.html",
        expected_artifacts=[{"path": "index.html", "type": "CREATE"}],
        acceptance_criteria=["EXISTS:index.html"],
    )
    assert td.scope_files == []
    assert td.protected_files == []
    assert td.edit_mode == "auto"
    assert td.allow_delete is False
    # round-trips
    td2 = TaskDefinition(**td.model_dump())
    assert td2.id == td.id


def test_task_definition_rejects_path_traversal_in_scope():
    for bad in (["../escape.txt"], ["sub/../../x.txt"], ["/abs.txt"], ["a\\..\\b.txt"]):
        try:
            TaskDefinition(
                id="task-1",
                description="x",
                expected_artifacts=[],
                acceptance_criteria=[],
                scope_files=bad,
            )
            raise AssertionError(f"expected ValueError for scope_files={bad}")
        except Exception as e:  # noqa: BLE001
            assert "Invalid path" in str(e), e

    # edit_mode must be one of the allowed literals
    try:
        TaskDefinition(id="t", description="x", expected_artifacts=[],
                       acceptance_criteria=[], edit_mode="force_merge")
        raise AssertionError("expected ValueError for bad edit_mode")
    except Exception as e:  # noqa: BLE001
        assert "edit_mode" in str(e), e


def test_task_definition_dedupes_and_normalizes_scope():
    td = TaskDefinition(
        id="t", description="x", expected_artifacts=[],
        acceptance_criteria=[], scope_files=["a/b.txt", "a\\b.txt", "a/b.txt"],
    )
    # windows sep normalized to '/', duplicate removed, stable order
    assert td.scope_files == ["a/b.txt"], td.scope_files


# --- 3.2 policy ----------------------------------------------------------------
def test_planner_sets_protected_files_when_project_ingested():
    project_files = ["index.html", "style.css", "app.js"]
    # task-2 targets style.css; the other two must become protected
    td = TaskDefinition(
        id="task-2",
        description="Edit button color in style.css",
        expected_artifacts=[{"path": "style.css", "type": "UPDATE"}],
        acceptance_criteria=["EXISTS:style.css"],
        scope_files=["style.css"],
    )
    out = apply_ingest_scope(td, project_files)
    assert out.scope_files == ["style.css"]
    assert out.protected_files == ["app.js", "index.html"], out.protected_files
    # original task untouched (pure copy)
    assert td.protected_files == []


def test_compute_protected_files_union_explicit():
    project_files = ["a.txt", "b.txt", "c.txt"]
    # explicit protected c.txt is kept even though not in project minus scope
    prot = compute_protected_files(project_files, scope_files=["a.txt"], existing_protected=["c.txt"])
    assert prot == ["b.txt", "c.txt"], prot


if __name__ == "__main__":
    failures = []
    for name, fn in [
        ("test_task_definition_defaults", test_task_definition_defaults),
        ("test_task_definition_rejects_path_traversal_in_scope", test_task_definition_rejects_path_traversal_in_scope),
        ("test_task_definition_dedupes_and_normalizes_scope", test_task_definition_dedupes_and_normalizes_scope),
        ("test_planner_sets_protected_files_when_project_ingested", test_planner_sets_protected_files_when_project_ingested),
        ("test_compute_protected_files_union_explicit", test_compute_protected_files_union_explicit),
    ]:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {name}: {e}")
            failures.append(name)
    if failures:
        print(f"{len(failures)} FAILURES: {failures}")
        raise SystemExit(1)
    print("OK")
