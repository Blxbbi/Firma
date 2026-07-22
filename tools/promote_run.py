#!/usr/bin/env python3
"""
tools/promote_run.py -- Phase 5 (Idee E/F): safe, MANUAL Copy/Promote helper.

NOT part of the Firma kernel. A human invokes this AFTER reviewing
archive/runs/<run_id>/audit.md. It copies the Firma-produced workspace project
into a NEW target directory and writes provenance. It never touches the original,
never overwrites, and never promotes in-place.

Usage:
  python tools/promote_run.py --run_id <run_id> --target_dir <dir> \
      [--workspace_dir <dir>] [--archive_dir <dir>]

Exit codes:
  0  promoted
  2  refused (safety guard: target exists, path traversal, or invalid run_id)
  3  source (workspace/<run_id>/project) missing
"""
import argparse
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _firma_commit() -> str:
    """Best-effort git short hash of the Firma repo (n/a if unavailable)."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parent.parent,
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return "n/a"


def _resolve_path(p: str) -> Path:
    # Reject obvious traversal attempts before resolving.
    if ".." in Path(p).parts:
        raise ValueError("path traversal not allowed")
    return Path(p).resolve()


def promote(run_id: str, target_dir: str, workspace_dir: str = None,
            archive_dir: str = None) -> int:
    # Resolve base dirs (defaults from engine settings; overridable for tests).
    if workspace_dir is None or archive_dir is None:
        try:
            from engine.settings import WORKSPACE_DIR, ARCHIVE_RUNS_DIR
            workspace_dir = workspace_dir or str(WORKSPACE_DIR)
            archive_dir = archive_dir or str(ARCHIVE_RUNS_DIR)
        except Exception:
            workspace_dir = workspace_dir or "workspace"
            archive_dir = archive_dir or str(Path("archive") / "runs")
    ws = Path(workspace_dir).resolve()
    arch = Path(archive_dir).resolve()

    # run_id hygiene: no traversal, no absolute path.
    if Path(run_id).is_absolute() or ".." in Path(run_id).parts:
        print("[promote] REFUSED: invalid run_id (traversal/absolute)", file=sys.stderr)
        return 2

    # Source must exist.
    source = ws / run_id / "project"
    if not source.exists() or not source.is_dir():
        print(f"[promote] REFUSED: source missing: {source}", file=sys.stderr)
        return 3

    # Target safety: resolve, reject traversal, refuse if it already exists.
    try:
        target = _resolve_path(target_dir)
    except ValueError:
        print("[promote] REFUSED: path traversal not allowed in target_dir", file=sys.stderr)
        return 2
    if target.exists():
        print(f"[promote] REFUSED: target already exists (no overwrite): {target}", file=sys.stderr)
        return 2

    # Copy exactly (the promoted dir IS the copy -- no excludes by default).
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(str(source), str(target))

    # Provenance: link back to the run + audit for traceability.
    audit = arch / run_id / "audit.md"
    provenance = target / "PROMOTED_FROM_RUN.txt"
    lines = [
        f"run_id={run_id}",
        f"promoted_at={datetime.now(timezone.utc).isoformat()}",
        f"audit={audit.resolve()}",
        f"firma_commit={_firma_commit()}",
    ]
    provenance.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"[promote] OK: {source} -> {target}")
    print(f"[promote] provenance: {provenance}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Safe manual Copy/Promote helper (Phase 5).")
    parser.add_argument("--run_id", required=True)
    parser.add_argument("--target_dir", required=True)
    parser.add_argument("--workspace_dir", default=None)
    parser.add_argument("--archive_dir", default=None)
    args = parser.parse_args(argv)
    return promote(args.run_id, args.target_dir, args.workspace_dir, args.archive_dir)


if __name__ == "__main__":
    sys.exit(main())
