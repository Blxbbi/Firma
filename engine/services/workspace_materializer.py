"""
Phase 2 (Idee A) — Workspace materializer (shared service).

Writes a CODER artifact's content into ``workspace/<run_id>/project/`` — the single
"source of truth" tree the scope verifier reads from. Both transports use this exact
function so the in-process path and the PiMesh Receiver share identical semantics:

  - run_pi_mesh.py  -> PiMeshReceiverLoop._inline_content (real worker files)
  - in-process E2E -> stub worker (simulates the Receiver)

Only acts when an ingest context exists for ``run_id`` (Phase 2 ingest mode). Guards
against absolute paths and ``..`` traversal (Security Boundary). Non-fatal on error so
a verifier glitch never breaks a run.
"""
import os

from engine.services.ingest_context import get_ingest


def materialize_to_workspace(run_id, rel_path, content, task_id=None):
    """Copy one artifact into the run's workspace project tree (truth).

    In ingest mode, only files listed in the task's scope_files are allowed to
    materialize. Out-of-scope artifacts (e.g. protected files written by a
    non-compliant CODER) are skipped with a warning so the scope verifier sees
    the original baseline state for those files.
    """
    if not run_id or content is None:
        return
    try:
        ing = get_ingest(run_id)
        if not ing:
            return
        rel = (rel_path or "").replace("\\", "/")
        if rel.startswith("/") or rel.startswith("\\") or ".." in rel:
            return

        # S4 scope gate: in ingest mode, only materialize files that are explicitly
        # in scope for the task that produced this artifact.
        if task_id:
            try:
                from engine.services.ingest_context import get_task_scope
                scope_for_task = get_task_scope(run_id, task_id)
                if scope_for_task:
                    allowed = set(scope_for_task.get("scope_files") or [])
                    if rel not in allowed:
                        logger.warning(
                            "[WorkspaceMaterializer] Skipping out-of-scope artifact %s for task %s (run %s) "
                            "(allowed=%s)",
                            rel, task_id, run_id, sorted(allowed),
                        )
                        return
            except Exception:
                pass

        root_abs = os.path.abspath(ing["workspace_root"])  # .../project
        # Phase 3 (Idee B): Researcher output lives in the SIBLING research/ dir
        # (.../research), NOT inside the project tree -- otherwise the read-only
        # guard would (correctly) flag it as project drift. The artifact path is
        # already relative to the run dir (e.g. "research/brief.md"), so the base
        # for research/ artifacts is the PARENT of project/ (.../workspace/<run_id>).
        # Everything else (CODER edits) goes into the project tree (truth).
        if rel.startswith("research/"):
            base_abs = os.path.abspath(os.path.join(root_abs, ".."))
        else:
            base_abs = root_abs
        dst_abs = os.path.abspath(os.path.join(base_abs, rel))
        if not (dst_abs == base_abs or dst_abs.startswith(base_abs + os.sep)):
            return
        os.makedirs(os.path.dirname(dst_abs), exist_ok=True)
        with open(dst_abs, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception:
        # Non-fatal: materialization must never break a run.
        pass
