"""
Phase 2 (Idee A) — Baseline-Manifest hasher.

Pure, side-effect-free except save_manifest(). Purpose-built to be unit-testable in
isolation and reused later by the Researcher (Phase 3: explore tree, compare snapshots)
and the Auditor (Phase 4: diff between runs).

Manifest schema
---------------
{
  "version": 1,
  "algo": "sha256",
  "root_dir": "<abspath>",
  "run_id": "<run_id|null>",
  "created_at": "<iso-utc>",
  "exclusions": ["node_modules", ...],
  "files": { "<relative_path>": "<sha256|symlink:<target>>", ... }
}

Determinism: the hash map (``files``) is identical for identical input trees and is
written with sorted keys. ``created_at`` is audit metadata only and is intentionally
excluded from determinism comparisons.
"""
import hashlib
import json
import os
from datetime import datetime, timezone

from engine.settings import INGEST_EXCLUSIONS

MANIFEST_VERSION = 1
ALGO = "sha256"


def hash_file(path: str) -> str:
    """SHA256 hex digest of a file's content (binary, chunked)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _iter_files(root_dir: str, exclusions):
    """Yield relative file paths under root_dir, pruning excluded components.

    Symlinked directories are not descended (followlinks=False). Symlinked files are
    yielded (the caller decides how to hash them).
    """
    exclusions = set(exclusions or ())
    for dirpath, dirnames, filenames in os.walk(root_dir, followlinks=False):
        kept = [d for d in dirnames if d not in exclusions]
        dirnames[:] = kept  # prune in-place so walk does not descend
        for fn in filenames:
            if fn in exclusions:
                continue
            full = os.path.join(dirpath, fn)
            yield os.path.relpath(full, root_dir)


def build_manifest(root_dir: str, exclusions=None, run_id=None) -> dict:
    """Build a baseline manifest for all files under root_dir."""
    exclusions = exclusions if exclusions is not None else INGEST_EXCLUSIONS
    files = {}
    for rel in _iter_files(root_dir, exclusions):
        full = os.path.join(root_dir, rel)
        if os.path.islink(full):
            # symlink: hash the normalized target string, do NOT follow into content
            files[rel] = "symlink:" + os.path.normpath(os.readlink(full))
        else:
            files[rel] = hash_file(full)
    return {
        "version": MANIFEST_VERSION,
        "algo": ALGO,
        "root_dir": os.path.abspath(root_dir),
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "exclusions": list(exclusions),
        "files": files,
    }


def save_manifest(manifest: dict, path: str) -> None:
    """Write manifest as sorted JSON (deterministic on disk)."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, sort_keys=True, indent=2)


def load_manifest(path: str) -> dict:
    """Load a manifest previously written by save_manifest."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def diff_manifests(baseline: dict, current: dict) -> dict:
    """Compare two manifests (same schema).

    Returns {"changed": [...], "added": [...], "removed": [...]} of relative paths,
    each list sorted for deterministic assertions.
    """
    b = baseline.get("files", {})
    c = current.get("files", {})
    changed = [p for p in b if p in c and b[p] != c[p]]
    added = [p for p in c if p not in b]
    removed = [p for p in b if p not in c]
    return {"changed": sorted(changed), "added": sorted(added), "removed": sorted(removed)}
