"""
Phase 2 (Idee A) - Step3.2: deterministic scope/protected policy.

Kernel-side (NOT the LLM). In V1 the planner does not compute scope/protected; the
kernel derives them deterministically after a project is ingested:

  protected_files = (all project files) - scope_files   [union any explicit protected]

`scope_files` per task comes from the task template / app-config (e.g. task-1 ->
index.html, task-2 -> style.css, task-3 -> app.js/game.js). This is the "Plumbing +
Policy beweisen, nicht LLM-Planqualitaet" approach.
"""
from typing import List, Optional, Set

from engine.models import TaskDefinition


def compute_protected_files(
    project_files: List[str],
    scope_files: List[str],
    existing_protected: Optional[List[str]] = None,
) -> List[str]:
    """V1 rule: everything in the project is protected except what is explicitly in scope."""
    scope: Set[str] = set(scope_files)
    base = set(project_files) - scope
    if existing_protected:
        base |= set(existing_protected)
    return sorted(base)


def apply_ingest_scope(task_def: TaskDefinition, project_files: List[str]) -> TaskDefinition:
    """Return a copy of task_def with protected_files filled (all - scope).

    scope_files is left untouched (it comes from the task template / app-config).
    If project_files is empty, the task is returned unchanged (no ingest context).
    """
    if not project_files:
        return task_def
    prot = compute_protected_files(project_files, task_def.scope_files, task_def.protected_files)
    data = task_def.model_dump()
    data["protected_files"] = prot
    return TaskDefinition(**data)
