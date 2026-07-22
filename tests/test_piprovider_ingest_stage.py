"""
F4 — PiProvider ingest project staging tests.

Verifies that PiProvider._stage_ingest_project_if_needed copies the ingest project
tree into a task-specific crew workdir (`.pi/work/<run_id>/<task_id>/project/`)
with the correct exclusions, and that non-CODER roles / missing ingest context
are no-ops.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.providers.pi_provider import PiProvider, _should_ignore_project_file


def _make_fake_ingest(workspace_root: str) -> dict:
    return {"workspace_root": workspace_root, "baseline_path": workspace_root + "_baseline.json"}


def test_should_ignore_project_file_excludes_pi_and_git_and_node_modules():
    assert _should_ignore_project_file(".pi") is True
    assert _should_ignore_project_file(".git") is True
    assert _should_ignore_project_file("node_modules") is True
    assert _should_ignore_project_file("__pycache__") is True
    assert _should_ignore_project_file(".gitignore") is True
    assert _should_ignore_project_file("style.css") is False
    assert _should_ignore_project_file("index.html") is False
    assert _should_ignore_project_file("") is True
    assert _should_ignore_project_file("../escape") is True
    assert _should_ignore_project_file("/abs/path") is True


def test_stage_copies_project_files_into_task_workdir():
    with tempfile.TemporaryDirectory() as tmp:
        crew_cwd = os.path.join(tmp, "crew")
        ws_root = os.path.join(tmp, "workspace", "run-1", "project")
        os.makedirs(ws_root)
        # Write fake project files + ignored dirs.
        open(os.path.join(ws_root, "style.css"), "w", encoding="utf-8").write("button{color:red}")
        open(os.path.join(ws_root, "index.html"), "w", encoding="utf-8").write("<html></html>")
        os.makedirs(os.path.join(ws_root, ".pi"))
        open(os.path.join(ws_root, ".pi", "meta.json"), "w", encoding="utf-8").write("{}")
        os.makedirs(os.path.join(ws_root, "node_modules", "foo"))
        open(os.path.join(ws_root, "node_modules", "foo", "bar.js"), "w", encoding="utf-8").write("x")

        run_id = "run-1"
        task_id = "task-1"
        # Patch get_ingest via the module-level import inside the static method.
        import engine.services.ingest_context as ic
        original_register = ic.register_ingest
        ic.register_ingest(run_id, ws_root, ws_root + "_baseline.json")
        try:
            result = PiProvider._stage_ingest_project_if_needed(
                role="CODER", run_id=run_id, task_id=task_id, crew_cwd=crew_cwd
            )
        finally:
            ic._INGEST.pop(run_id, None)

        assert result is not None
        expected_workdir = os.path.join(crew_cwd, ".pi", "work", run_id, task_id, "project")
        assert result == expected_workdir
        assert os.path.isdir(expected_workdir)
        # Project files present.
        assert os.path.isfile(os.path.join(expected_workdir, "style.css"))
        assert os.path.isfile(os.path.join(expected_workdir, "index.html"))
        # Ignored dirs/files excluded.
        assert not os.path.exists(os.path.join(expected_workdir, ".pi"))
        assert not os.path.exists(os.path.join(expected_workdir, "node_modules"))


def test_stage_copies_project_for_researcher_role():
    with tempfile.TemporaryDirectory() as tmp:
        crew_cwd = os.path.join(tmp, "crew")
        ws_root = os.path.join(tmp, "workspace", "run-1", "project")
        os.makedirs(ws_root)
        open(os.path.join(ws_root, "style.css"), "w", encoding="utf-8").write("x")

        import engine.services.ingest_context as ic
        ic.register_ingest("run-1", ws_root, ws_root + "_baseline.json")
        try:
            result = PiProvider._stage_ingest_project_if_needed(
                role="RESEARCHER", run_id="run-1", task_id="task-1", crew_cwd=crew_cwd
            )
        finally:
            ic._INGEST.pop("run-1", None)

        assert result is not None
        expected_workdir = os.path.join(crew_cwd, ".pi", "work", "run-1", "task-1", "project")
        assert result == expected_workdir
        assert os.path.isfile(os.path.join(expected_workdir, "style.css"))


def test_stage_is_noop_for_non_coder_researcher_roles():
    with tempfile.TemporaryDirectory() as tmp:
        crew_cwd = os.path.join(tmp, "crew")
        ws_root = os.path.join(tmp, "workspace", "run-1", "project")
        os.makedirs(ws_root)
        open(os.path.join(ws_root, "style.css"), "w", encoding="utf-8").write("x")

        import engine.services.ingest_context as ic
        ic.register_ingest("run-1", ws_root, ws_root + "_baseline.json")
        try:
            for role in ("PLANNER", "REVIEWER"):
                result = PiProvider._stage_ingest_project_if_needed(
                    role=role, run_id="run-1", task_id="task-1", crew_cwd=crew_cwd
                )
                assert result is None, f"expected no staging for {role}"
                assert not os.path.exists(os.path.join(crew_cwd, ".pi", "work"))
        finally:
            ic._INGEST.pop("run-1", None)


def test_stage_is_noop_when_no_ingest_context():
    with tempfile.TemporaryDirectory() as tmp:
        crew_cwd = os.path.join(tmp, "crew")
        result = PiProvider._stage_ingest_project_if_needed(
            role="CODER", run_id="missing-run", task_id="task-1", crew_cwd=crew_cwd
        )
        assert result is None
        assert not os.path.exists(os.path.join(crew_cwd, ".pi"))


if __name__ == "__main__":
    failures = []
    for fn in (
        test_should_ignore_project_file_excludes_pi_and_git_and_node_modules,
        test_stage_copies_project_files_into_task_workdir,
        test_stage_copies_project_for_researcher_role,
        test_stage_is_noop_for_non_coder_researcher_roles,
        test_stage_is_noop_when_no_ingest_context,
    ):
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:
            failures.append((fn.__name__, e))
            print(f"FAIL {fn.__name__}: {e}")
    if failures:
        print(f"\n{len(failures)} failure(s)")
        sys.exit(1)
    print("\nAll tests passed.")
