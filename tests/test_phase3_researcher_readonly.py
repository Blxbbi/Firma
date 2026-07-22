"""
Phase 3 (Idee B) - Step3.3: Read-only verifier for the Researcher (unit/light integration).

Run via: ./tools/safe_test.sh tests/test_phase3_researcher_readonly.py

Covers:
  - Researcher may write under research/ (outside the project tree) -> ok.
  - Researcher modifying a project file -> RESEARCHER_DRIFT (deterministic).
  - From-scratch (no ingest context) -> pass-through.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.services.ingest import setup_ingest_run
from engine.services.ingest_context import get_ingest
from engine.services.workspace_materializer import materialize_to_workspace
from engine.services.verifiers.research_readonly_verifier import verify_researcher_readonly

INDEX = "<html></html>"
STYLE = "button { background: red; }"


def test_researcher_readonly_ok_and_drift():
    tmp = Path(tempfile.mkdtemp())
    fixture = tmp / "fixture"
    fixture.mkdir()
    (fixture / "index.html").write_text(INDEX, encoding="utf-8")
    (fixture / "style.css").write_text(STYLE, encoding="utf-8")
    ws = tmp / "workspace"
    run_id = "r-ro-1"
    setup_ingest_run(run_id, src=str(fixture), workspace_dir=str(ws))
    ing = get_ingest(run_id)
    ws_root = ing["workspace_root"]

    # 1) Researcher writes brief under research/ (sibling of project/, ignored by check)
    research_dir = os.path.join(os.path.dirname(ws_root), "research")
    os.makedirs(research_dir, exist_ok=True)
    with open(os.path.join(research_dir, "brief.md"), "w", encoding="utf-8") as f:
        f.write("# Brief")

    ok, code, violations = verify_researcher_readonly(run_id=run_id)
    assert ok, (code, violations)

    # 2) Researcher ALSO modified a project file -> drift
    materialize_to_workspace(run_id, "index.html", INDEX + "<!-- drift -->")
    ok2, code2, violations2 = verify_researcher_readonly(run_id=run_id)
    assert not ok2, (code2, violations2)
    assert "index.html" in violations2, violations2
    assert code2 == "RESEARCHER_DRIFT", code2


def test_researcher_readonly_no_ingest_passthrough():
    ok, code, violations = verify_researcher_readonly(run_id="does-not-exist")
    assert ok and code == "NO_INGEST", (ok, code)


if __name__ == "__main__":
    failures = []
    try:
        test_researcher_readonly_ok_and_drift()
        print("PASS test_researcher_readonly_ok_and_drift")
    except Exception as e:  # noqa: BLE001
        print(f"FAIL test_researcher_readonly_ok_and_drift: {e}")
        failures.append("drift")

    try:
        test_researcher_readonly_no_ingest_passthrough()
        print("PASS test_researcher_readonly_no_ingest_passthrough")
    except Exception as e:  # noqa: BLE001
        print(f"FAIL test_researcher_readonly_no_ingest_passthrough: {e}")
        failures.append("passthrough")

    if failures:
        print(f"{len(failures)} FAILURES: {failures}")
        raise SystemExit(1)
    print("OK")
