"""
Phase 3 (Idee B) - Read-only verifier for the Researcher.

The Researcher must NOT modify the ingested project tree. After a RESEARCH_COMPLETE
we diff the project/ subtree (workspace_root, from the ingest context) against the
ingest baseline manifest. Any change/add/remove in the project tree is a drift
violation. Writes under the sibling research/ directory are OUTSIDE the project tree
and therefore ignored by this check (they are the Researcher's legitimate output).

Defense-in-depth: the Guardian also enforces the artifact-path policy (Step3.2); the
baseline-diff gate here is the authoritative second layer.
"""
import os
from typing import Tuple, List, Any

from engine.settings import INGEST_EXCLUSIONS
from engine.services.baseline_manifest import build_manifest, load_manifest, diff_manifests
from engine.services.ingest_context import get_ingest


def verify_researcher_readonly(
    run_id: str = None,
    workspace_root: str = None,
    baseline_path: str = None,
) -> Tuple[bool, str, List[str]]:
    """Return (ok, code, violations).

    violations is the list of changed/added/removed relative paths in the project tree.
    In from-scratch runs (no ingest context / no baseline) the check is a pass-through.
    """
    if run_id:
        ing = get_ingest(run_id)
        if not ing:
            return True, "NO_INGEST", []
        workspace_root = ing["workspace_root"]
        baseline_path = ing["baseline_path"]
    if not workspace_root or not baseline_path or not os.path.exists(baseline_path):
        return True, "NO_BASELINE", []

    baseline = load_manifest(baseline_path)
    current = build_manifest(workspace_root, exclusions=INGEST_EXCLUSIONS)
    diff = diff_manifests(baseline, current)
    violations = list(diff["changed"]) + list(diff["added"]) + list(diff["removed"])
    ok = len(violations) == 0
    code = "RESEARCHER_DRIFT" if not ok else "OK"
    return ok, code, violations
