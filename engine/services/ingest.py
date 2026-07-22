"""
Phase 2 (Idee A) — Project ingest.

Copies an existing project folder into ``workspace/<run_id>/project/`` (the "running
codebase", owned by the kernel as single-writer) and writes a baseline manifest
next to it at ``workspace/<run_id>/baseline_manifest.json``. This is the stable
location the Step2 scope/protected verifier will read from.

Step1 scope is intentionally isolated:
  - NO workspace-drift verifier
  - NO scope_files/protected_files (Planner/Spec schema change happens in Step3)
  - NO CODER prompt change (wiring into run_snake.py happens in a later step)

The copy is traversal-safe: every resolved destination path is asserted to stay inside
the destination root (handles crafted ``..`` names and symlinks that point outside src).
"""
import os
import shutil

from engine.settings import WORKSPACE_DIR, INGEST_EXCLUSIONS, INGEST_PROJECT_DIR
from engine.services.baseline_manifest import build_manifest, save_manifest
from engine.services import ingest_context


def _safe_join(root: str, rel: str) -> str:
    """Join root + rel, raising ValueError if rel escapes root (path traversal)."""
    root_abs = os.path.abspath(root)
    target = os.path.abspath(os.path.join(root_abs, rel))
    root_norm = os.path.normpath(root_abs)
    target_norm = os.path.normpath(target)
    if target_norm != root_norm and not target_norm.startswith(root_norm + os.sep):
        raise ValueError(f"Path traversal detected: {rel!r} -> {target}")
    return target


def copy_project_tree(src: str, dst: str, exclusions=None) -> None:
    """Recursively copy src -> dst, skipping excluded dir/file names, no traversal."""
    exclusions = set(exclusions if exclusions is not None else INGEST_EXCLUSIONS)
    src_abs = os.path.abspath(src)
    dst_abs = os.path.abspath(dst)
    os.makedirs(dst_abs, exist_ok=True)

    for dirpath, dirnames, filenames in os.walk(src_abs, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in exclusions]
        for fn in filenames:
            if fn in exclusions:
                continue
            src_file = os.path.join(dirpath, fn)
            rel = os.path.relpath(src_file, src_abs)
            dst_file = _safe_join(dst_abs, rel)  # raises on traversal
            os.makedirs(os.path.dirname(dst_file), exist_ok=True)
            if os.path.islink(src_file):
                # copy symlink as symlink (do NOT follow into target content)
                if os.path.lexists(dst_file):
                    os.remove(dst_file)
                os.symlink(os.readlink(src_file), dst_file)
            else:
                shutil.copy2(src_file, dst_file)


def ingest_project(src: str, run_id: str, workspace_dir=None) -> dict:
    """Copy src into workspace/<run_id>/project/ and write the baseline manifest.

    Returns the baseline manifest dict. Manifest location:
    ``workspace/<run_id>/baseline_manifest.json`` (stable for the Step2 verifier).

    Note: the source folder itself is never mutated (read-only ingest). Only the
    workspace copy is touched.
    """
    workspace_dir = workspace_dir or str(WORKSPACE_DIR)
    project_root = os.path.join(workspace_dir, run_id, "project")
    copy_project_tree(src, project_root, INGEST_EXCLUSIONS)
    manifest = build_manifest(project_root, INGEST_EXCLUSIONS, run_id=run_id)
    manifest_path = os.path.join(workspace_dir, run_id, "baseline_manifest.json")
    save_manifest(manifest, manifest_path)
    return manifest


def setup_ingest_run(run_id: str, src: str = None, workspace_dir: str = None):
    """Ingest a project for a run and register its context.

    `src` defaults to ``settings.INGEST_PROJECT_DIR`` (the v1 trigger env). The source
    folder is never mutated; only the workspace copy is touched. Returns the baseline
    manifest dict, or None if no source is configured.
    """
    src = src or INGEST_PROJECT_DIR
    if not src:
        return None
    manifest = ingest_project(src, run_id, workspace_dir=workspace_dir)
    ws = workspace_dir or str(WORKSPACE_DIR)
    ingest_context.register_ingest(
        run_id,
        os.path.join(ws, run_id, "project"),
        os.path.join(ws, run_id, "baseline_manifest.json"),
    )
    return manifest
