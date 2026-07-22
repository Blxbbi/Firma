"""
Phase 2 (Idee A) — Step2: deterministic scope/protected verifier ("Rest bleibt").

Pure service, no DB, no async. Given the running workspace tree and the baseline
manifest captured at ingest (Step1), it recomputes the current manifest and checks
the delta against the edit-contract (scope_files / protected_files).

Failure codes (ok=False):
  PROTECTED_VIOLATION  - a protected file was changed or deleted
  SCOPE_VIOLATION      - a file outside scope_files was changed or deleted
  UNEXPECTED_NEW_FILE  - a new file appears outside scope_files (and allowlist)
  BASELINE_MISSING     - baseline manifest missing/unparseable (guard cannot run)

This is the deterministic guard from Vision §2.4 / Plan Phase2 §5. It deliberately
does NOT trust the worker's self-report: it re-reads the live workspace tree.

Deferred to Step3 (Planner/Spec schema): edit_mode (force_edit/force_create) and
explicit delete-allowance. Step2 covers exactly the four rules from the Step2 freigabe.
"""
import json
from dataclasses import dataclass
from typing import List, Optional, Set

from engine.services.baseline_manifest import (
    build_manifest,
    load_manifest,
    diff_manifests,
)
from engine.settings import INGEST_EXCLUSIONS


@dataclass
class ScopeVerifyResult:
    ok: bool
    code: Optional[str]
    changed: List[str]
    deleted: List[str]
    new: List[str]
    report: str

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "code": self.code,
            "changed": self.changed,
            "deleted": self.deleted,
            "new": self.new,
            "report": self.report,
        }


def verify_scope(
    workspace_root: str,
    baseline_manifest_path: str,
    scope_files: Optional[List[str]] = None,
    protected_files: Optional[List[str]] = None,
    exclusions: Optional[List[str]] = None,
    allow_new_files: Optional[List[str]] = None,
) -> ScopeVerifyResult:
    # 1) load baseline (Step2 rule 4: missing/broken -> BASELINE_MISSING)
    try:
        baseline = load_manifest(baseline_manifest_path)
    except (FileNotFoundError, json.JSONDecodeError, KeyError, ValueError) as e:
        return ScopeVerifyResult(
            ok=False,
            code="BASELINE_MISSING",
            changed=[],
            deleted=[],
            new=[],
            report=f"baseline manifest missing/unparseable: {e}",
        )

    # use the SAME exclusions the baseline was built with (deterministic;
    # e.g. node_modules changes are ignored because they were excluded at ingest)
    eff_exclusions = (
        exclusions if exclusions is not None else baseline.get("exclusions") or list(INGEST_EXCLUSIONS)
    )

    # 2) recompute current manifest over the live workspace
    current = build_manifest(workspace_root, eff_exclusions)

    # 3) diff
    d = diff_manifests(baseline, current)
    changed = d["changed"]                                       # hash differs
    deleted = d["removed"]                                       # in baseline, absent now
    new = d["added"]                                             # present now, absent in baseline

    scope: Set[str] = set(scope_files or [])
    protected: Set[str] = set(protected_files or [])
    allow_new: Set[str] = set(allow_new_files or [])

    # Rule 1: protected files must not change or be deleted
    prot_hit = [f for f in changed if f in protected] + [f for f in deleted if f in protected]
    if prot_hit:
        return ScopeVerifyResult(
            ok=False,
            code="PROTECTED_VIOLATION",
            changed=changed,
            deleted=deleted,
            new=new,
            report=f"protected files changed/deleted: {sorted(set(prot_hit))}",
        )

    # Rule 2: changes/deletions outside scope -> violation
    out_changes = [f for f in changed if f not in scope]
    out_deletes = [f for f in deleted if f not in scope]
    if out_changes or out_deletes:
        return ScopeVerifyResult(
            ok=False,
            code="SCOPE_VIOLATION",
            changed=changed,
            deleted=deleted,
            new=new,
            report=f"out-of-scope changes: {out_changes}; out-of-scope deletions: {out_deletes}",
        )

    # Rule 3: new files outside scope (and outside allowlist) -> violation
    unexpected_new = [f for f in new if f not in scope and f not in allow_new]
    if unexpected_new:
        return ScopeVerifyResult(
            ok=False,
            code="UNEXPECTED_NEW_FILE",
            changed=changed,
            deleted=deleted,
            new=new,
            report=f"unexpected new files: {sorted(set(unexpected_new))}",
        )

    return ScopeVerifyResult(
        ok=True, code=None, changed=changed, deleted=deleted, new=new, report="scope ok"
    )
