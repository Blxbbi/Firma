"""
Phase 5 (Idee E/F) - Tests for tools/promote_run.py (safe manual Copy/Promote).

Run via: ./tools/safe_test.sh tests/test_phase5_promote_tool.py

The tool is exercised at the function level (promote(...)) -- deterministic, no
subprocess flakiness, no engine/LLM. Covers: correct copy, provenance file,
refusal on overwrite, refusal on path traversal, missing source.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.promote_run import promote


def _seed(tmp: Path, run_id: str, with_source=True, with_audit=True):
    ws = tmp / "workspace"
    arch = tmp / "archive"
    if with_source:
        proj = ws / run_id / "project"
        proj.mkdir(parents=True)
        (proj / "index.html").write_text("<html></html>", encoding="utf-8")
        (proj / "style.css").write_text("button { color: red; }", encoding="utf-8")
    if with_audit:
        adir = arch / run_id
        adir.mkdir(parents=True)
        (adir / "audit.md").write_text(f"# Run Audit: {run_id}\n", encoding="utf-8")
    return ws, arch


def _test_copies_project_into_new_target():
    tmp = Path(tempfile.mkdtemp())
    run_id = "run-promo-001"
    ws, arch = _seed(tmp, run_id)
    target = tmp / "out" / "v2"
    rc = promote(run_id, str(target), workspace_dir=str(ws), archive_dir=str(arch))
    assert rc == 0, f"expected 0, got {rc}"
    assert (target / "index.html").exists()
    assert (target / "style.css").exists()
    # source unchanged (tool only reads it)
    assert (ws / run_id / "project" / "style.css").exists()


def _test_writes_provenance_file():
    tmp = Path(tempfile.mkdtemp())
    run_id = "run-promo-002"
    ws, arch = _seed(tmp, run_id)
    target = tmp / "out" / "v2"
    rc = promote(run_id, str(target), workspace_dir=str(ws), archive_dir=str(arch))
    assert rc == 0
    prov = target / "PROMOTED_FROM_RUN.txt"
    assert prov.exists(), "PROMOTED_FROM_RUN.txt missing"
    text = prov.read_text(encoding="utf-8")
    assert f"run_id={run_id}" in text, "run_id missing in provenance"
    assert "audit=" in text and "audit.md" in text, "audit link missing in provenance"
    assert "firma_commit=" in text, "firma_commit missing in provenance"


def _test_refuses_overwrite():
    tmp = Path(tempfile.mkdtemp())
    run_id = "run-promo-003"
    ws, arch = _seed(tmp, run_id)
    target = tmp / "out" / "v2"
    target.mkdir(parents=True)
    (target / "existing.txt").write_text("do not touch", encoding="utf-8")
    rc = promote(run_id, str(target), workspace_dir=str(ws), archive_dir=str(arch))
    assert rc == 2, f"expected refusal 2, got {rc}"
    # target unchanged: its pre-existing file is intact, no provenance written
    assert (target / "existing.txt").read_text(encoding="utf-8") == "do not touch"
    assert not (target / "PROMOTED_FROM_RUN.txt").exists()


def _test_refuses_traversal():
    tmp = Path(tempfile.mkdtemp())
    run_id = "run-promo-004"
    ws, arch = _seed(tmp, run_id)
    # traversal in target_dir -> refused, nothing written
    rc = promote(run_id, str(tmp / "x" / ".." / "evil"), workspace_dir=str(ws), archive_dir=str(arch))
    assert rc == 2, f"expected refusal 2, got {rc}"
    assert not (tmp / "evil").exists(), "traversal created a directory"


def _test_missing_source():
    tmp = Path(tempfile.mkdtemp())
    run_id = "run-promo-005"
    ws, arch = _seed(tmp, run_id, with_source=False, with_audit=True)
    target = tmp / "out" / "v2"
    rc = promote(run_id, str(target), workspace_dir=str(ws), archive_dir=str(arch))
    assert rc == 3, f"expected missing-source 3, got {rc}"
    assert not target.exists(), "target should not be created when source missing"


def _main():
    failures = []
    for name, fn in [
        ("copies_project_into_new_target", _test_copies_project_into_new_target),
        ("writes_provenance_file", _test_writes_provenance_file),
        ("refuses_overwrite", _test_refuses_overwrite),
        ("refuses_traversal", _test_refuses_traversal),
        ("missing_source", _test_missing_source),
    ]:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {name}: {e}")
            failures.append(name)
    if failures:
        print(f"\n{len(failures)} FAILURES: {failures}")
        raise SystemExit(1)
    print("\nALL PROMOTE TOOL TESTS PASS")


if __name__ == "__main__":
    _main()
