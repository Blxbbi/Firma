import logging
from typing import List, Optional, Dict, Any
import asyncio
import re
import os
from engine.repository import MessageRepository
from engine.models import Message, MessageType, Task, MessageHeader, Run
from engine.prompt_loader import get_prompt_loader

logger = logging.getLogger(__name__)


# --- Pure gating logic (no DB, no SQLAlchemy) ---
# Terminal states for a CODER task in ingest mode. Once a CODER task reaches one
# of these states, the next CODER task may start (workspace baseline is stable).
CODER_GATE_TERMINAL_STATES = {
    "COMPLETE",
    "FAILED",
    "FAILED_ITERATION_LIMIT",
    "CANCELLED",
}

# Non-terminal states that block the next CODER task.
# NOTE: READY is intentionally excluded — a READY CODER has not started yet,
# so it cannot block another READY CODER from starting. The gate only blocks
# when an *earlier* CODER is already in progress or under review.
CODER_GATE_BLOCKING_STATES = {
    "CLAIMED",
    "IN_PROGRESS",
    "SUBMITTED",
    "VERIFYING",
    "REVIEWING",
}


def is_coder_gate_blocked(tasks: List[Dict[str, Any]], current_task_id: str) -> Optional[Dict[str, str]]:
    """Pure function: decide whether a CODER task must wait for another CODER.

    Args:
        tasks: list of task dicts with at least keys `id`, `assigned_role`, `state`.
        current_task_id: the task we want to dispatch now (excluded from check).

    Returns:
        Blocking task dict `{"id": ..., "state": ...}` if another non-terminal
        CODER task exists, else None.
    """
    for task in tasks:
        if task.get("id") == current_task_id:
            continue
        if task.get("assigned_role") != "CODER":
            continue
        state = task.get("state")
        if state in CODER_GATE_BLOCKING_STATES:
            return {"id": task["id"], "state": state}
    return None


def _extract_filenames_from_criteria(criteria: List[str]) -> List[str]:
    """
    Extract filenames from acceptance criteria.

    Uses regex to find patterns like:
    - "index.html"
    - "style.css"
    - "app.js"

    Returns deduplicated list of filenames.
    """
    filenames: List[str] = []

    for criterion in criteria:
        # Match word characters, hyphens, followed by a known extension
        found = re.findall(r"\b[\w\-]+\.(?:html|css|js|json|md|txt|svg|png|jpg|gif)\b", criterion)
        filenames.extend(found)

    # Deduplicate while preserving order
    seen: List[str] = []
    for f in filenames:
        if f not in seen:
            seen.append(f)

    return seen


def _extend_scope_from_criteria(task_definition: Dict[str, Any], run_id: str) -> Dict[str, Any]:
    """
    Extend CODER scope based on files mentioned in acceptance criteria.

    If a criterion mentions a file that already exists in the project,
    add it to scope_files (read-only access). If it doesn't exist yet,
    add it to expected_artifacts.

    This prevents the common Planner-Coder mismatch where a criterion like
    "style.css linked from index.html" forces the CODER to modify index.html
    even though it's not in expected_artifacts.
    """
    if not task_definition.get("acceptance_criteria"):
        return task_definition

    # Extract filenames mentioned in criteria
    mentioned_files = _extract_filenames_from_criteria(
        task_definition.get("acceptance_criteria", [])
    )

    if not mentioned_files:
        return task_definition

    # Get current scopes
    scope_files: List[str] = list(task_definition.get("scope_files", []))
    expected_artifacts: List[Dict[str, Any]] = list(
        task_definition.get("expected_artifacts", [])
    )
    expected_paths = {a.get("path", "") for a in expected_artifacts if isinstance(a, dict)}

    # Try to find existing project files via ingest context
    existing_project_files: List[str] = []
    try:
        from engine.services.ingest_context import get_ingest
        ing = get_ingest(run_id)
        if ing:
            workspace_root = ing.get("workspace_root", "")
            project_dir = os.path.join(workspace_root, "project")
            if os.path.isdir(project_dir):
                for root, dirs, files in os.walk(project_dir):
                    for fname in files:
                        rel = os.path.relpath(os.path.join(root, fname), project_dir)
                        existing_project_files.append(rel.replace(os.sep, "/"))
    except Exception:
        pass

    # Extend scope for each mentioned file
    for file in mentioned_files:
        # Normalize path
        file = file.replace("\\", "/").strip()

        if not file:
            continue

        # Already in expected_artifacts? Skip
        if file in expected_paths:
            continue

        # Already in scope_files? Skip
        if file in scope_files:
            continue

        if file in existing_project_files:
            # File exists in project → allow read-only access
            scope_files.append(file)
            logger.info(
                "[ScopeGuard] Auto-extending scope_files for %s: added %s (exists in project)",
                task_definition.get("task_id", "?"),
                file,
            )
        else:
            # File doesn't exist yet → add to expected_artifacts
            expected_artifacts.append({"path": file, "type": "CREATE"})
            logger.info(
                "[ScopeGuard] Auto-extending expected_artifacts for %s: added %s (mentioned in criteria)",
                task_definition.get("task_id", "?"),
                file,
            )

    # Update task_definition
    task_definition["scope_files"] = scope_files
    task_definition["expected_artifacts"] = expected_artifacts

    return task_definition


class Scheduler:
    """
    Minimalist Deterministic Scheduler (v0).
    Responsible for the 'Impulse' of the engine.
    """

    def __init__(self, db_manager, messenger_callback=None):
        self.db = db_manager
        self.messenger_callback = messenger_callback
        self.ack_timeout = 900  # Raised to 15min to accommodate slower workers

    async def _find_blocking_coder_task(self, session, run_id: str, exclude_task_id: str) -> Optional[dict]:
        """In ingest mode, find a non-terminal CODER task that blocks dispatch.

        Terminal states = COMPLETE / FAILED / FAILED_ITERATION_LIMIT / CANCELLED.
        All other states block the next CODER task so the workspace baseline stays
        deterministic (only accepted prior CODER commits are materialized).

        Refactored: delegates the decision to the pure `is_coder_gate_blocked()`
        so the gating logic is unit-testable without SQLAlchemy mocks.
        """
        from engine.models import Task
        from sqlalchemy import select

        result = await session.execute(
            select(Task.id, Task.assigned_role, Task.state)
            .where(
                Task.run_id == run_id,
                Task.id != exclude_task_id,
            )
            .order_by(Task.id)
        )
        tasks = [
            {"id": row.id, "assigned_role": row.assigned_role, "state": row.state}
            for row in result.all() or []
        ]
        return is_coder_gate_blocked(tasks, exclude_task_id)

    async def recover_stale_claims(self, run_id: str = None):
        """
        Production-Grade: Resets tasks stuck in CLAIMED/PROCESSING state to READY
        based on lease expiration.
        """
        from engine.models import Task
        from sqlalchemy import update, or_
        from datetime import datetime, timezone
        
        now = datetime.now(timezone.utc)
        
        async with self.db.session_scope() as session:
            query = update(Task).where(
                Task.state.in_(["CLAIMED", "PROCESSING"]),
                (Task.lease_expires_at < now) | (Task.lease_expires_at == None)
            )
            
            if run_id:
                query = query.where(Task.run_id == run_id)
            
            result = await session.execute(
                query.values(
                    state="READY", 
                    assigned_role=None, 
                    assigned_worker=None, 
                    lease_expires_at=None
                )
            )
            if result.rowcount > 0:
                logger.info(f"[Recovery] Recovered {result.rowcount} stale leases.")
            else:
                logger.debug("[Recovery] No stale leases found.")

    async def run_tick(self, run_id: str):
        """A single scheduling cycle for a specific run."""
        await self.assign_unassigned_ready_tasks(run_id)

    async def assign_unassigned_ready_tasks(self, run_id: str):
        """A single scheduling cycle for a specific run."""
        logger.debug(f"Scheduler tick starting for run {run_id}...")
        
        try:
            async with self.db.session_scope() as session:
                repo = MessageRepository(session)
                
                # 1. Handle Assignments (Impulse Phase)
                await self._handle_assignments(session, repo, run_id)
                
                # --- SURGICAL STATE FORENSICS ---
                # Disabled by default to prevent log flooding
                # from sqlalchemy import select
                # from engine.models import Task
                # all_tasks = await session.execute(select(Task.id, Task.state).where(Task.run_id == run_id))
                # rows = all_tasks.all()
                # if not rows:
                #     logger.info(f"SCHEDULER FORENSICS: No tasks found for run {run_id}.")
                # else:
                #     for row in rows:
                #         logger.info(f"SCHEDULER SEES (run {run_id}): id={row.id}, state={row.state!r}, type={type(row.state)}")
                # --------------------------------
        except Exception as e:
            logger.error(f"Scheduler tick encountered a critical error: {str(e)}", exc_info=True)
            raise
        
        logger.debug("Scheduler tick finished.")

    async def _handle_assignments(self, session, repo, run_id: str):
        """Finds READY tasks and assigns them within a specific run."""
        from engine.models import Project
        from sqlalchemy import select
        
        # --- CODER Gate (always active) ---
        # Serialize CODER tasks to prevent provider rate limits and workspace races.
        # In ingest mode this also keeps per-task baselines deterministic.
        # In greenfield mode this prevents parallel CODER workers from hammering the provider.
        coder_gate_active = True
        # ---

        # Strict serialization: only one CODER task per scheduler tick.
        # This prevents the race where multiple READY CODER tasks are fetched before
        # any of them is transitioned to CLAIMED.
        coder_assigned_this_tick = False
        # ---

        # Track what happened this tick for a single concise summary.
        assigned_this_tick = []   # list of task IDs
        delayed_this_tick = []    # list of (task_id, reason)
        
        # Remember the last logged delay signature so we only log when
        # the actual blocking set changes (not every 0.5s tick).
        last_delay_signature = getattr(self, "_last_delay_signature", None)
        current_delay_signature = None

        # Industrial Isolation: Filter by run_id instead of limit(1)
        proj_res = await session.execute(select(Project).where(Project.run_id == run_id).limit(1))
        project = proj_res.scalars().first()
        if not project or not project.active_plan_id:
            logger.info(f"No active project or plan_id found for run {run_id}. Skipping assignments.")
            return
            
        active_plan_id = project.active_plan_id
        
        # Fetch project config to get the initial prompt
        run_res = await session.execute(select(Run).where(Run.id == run_id))
        run_obj = run_res.scalars().first()
        project_prompt = run_obj.config_json.get("prompt", "No prompt provided") if run_obj else "No prompt provided"

        # FIX: Passing run_id to get_unassigned_ready_tasks
        ready_tasks = await repo.get_unassigned_ready_tasks(session, run_id, active_plan_id)
        if not ready_tasks:
            return

        for task in ready_tasks:
            if task.run_id != run_id:
                continue

            # --- CODER Gate ---
            # Block CODER dispatch when another CODER task in the same run is
            # still non-terminal. This serializes CODER work to prevent provider
            # rate limits and workspace races (applies in all modes).
            if coder_gate_active and task.assigned_role == "CODER":
                # Strict serialization: only allow ONE CODER assignment per scheduler tick.
                # This prevents the race where multiple READY CODER tasks are fetched
                # before any of them is transitioned to CLAIMED.
                if coder_assigned_this_tick:
                    delayed_this_tick.append((task.id, "another CODER already assigned this tick"))
                    continue
                blocking = await self._find_blocking_coder_task(session, run_id, task.id)
                if blocking:
                    blocking_id = blocking["id"]
                    blocking_state = blocking["state"]
                    delayed_this_tick.append((task.id, f"{blocking_id} is still {blocking_state}"))
                    continue
                coder_assigned_this_tick = True
            # ---

            # FIX: Passing run_id to assign_task_with_timeout
            success = await repo.assign_task_with_timeout(session, run_id, task.id, self.ack_timeout)
            if success:
                assigned_this_tick.append(task.id)
                logger.info(f"Task {task.id} assigned. Sending TASK_ASSIGNMENT.")
                
                if self.messenger_callback:
                    logger.debug(f"[Scheduler] Dispatching task {task.id}")
                    prev_fb = getattr(task, "last_review_feedback", None)
                    if prev_fb and task.assigned_role == "CODER":
                        logger.info(f"[Collaborative] CODER retry for {task.id} carries previous feedback")
                    assignment_payload = {
                        "event": "TASK_ASSIGNMENT",
                        "run_id": run_id,
                        "task_id": task.id,
                        "role": task.assigned_role,
                        "state_revision": task.state_revision,
                        "prompt": project_prompt,
                        "task_definition": {
                            "task_id": task.id,
                            "description": task.description,
                            "acceptance_criteria": task.acceptance_criteria,
                            "expected_artifacts": task.expected_artifacts or [],
                            "previous_feedback": prev_fb
                        }
                    }
                    # Ingest mode: inject scope/protected files so the CODER spec can
                    # render an explicit SCOPE CONTRACT section (S1 fix).
                    if task.assigned_role == "CODER":
                        try:
                            from engine.services.ingest_context import get_task_scope
                            scope = get_task_scope(run_id, task.id)
                            if scope:
                                assignment_payload["task_definition"]["scope_files"] = scope.get("scope_files") or []
                                assignment_payload["task_definition"]["protected_files"] = scope.get("protected_files") or []
                        except Exception as exc:
                            logger.warning("[Scheduler] Failed to load task scope for %s: %s", task.id, exc)
                    # Per-task baseline snapshot for scoped verification (fixes false positives
                    # when task-2 sees task-1's legitimate changes as protected drift).
                    if task.assigned_role == "CODER":
                        try:
                            from engine.services.task_baseline import save_task_baseline
                            save_task_baseline(run_id, task.id, task.state_revision)
                        except Exception as exc:
                            logger.warning("[Scheduler] Failed to save task baseline for %s: %s", task.id, exc)
                    # Phase 3 (Idee B): ground the PLANNER on the Researcher's read-only
                    # briefing. Handoff strictly via workspace file (no P2P). CODER tasks
                    # created by the plan inherit the same briefing pointer below.
                    if task.assigned_role == "PLANNER":
                        assignment_payload.setdefault("task_definition", {})["research_brief"] = "research/brief.md"
                        research_context_template = get_prompt_loader().load('planner', 'pimesh_research_context')
                        assignment_payload["prompt"] = research_context_template.format(
                            project_prompt=project_prompt,
                            run_id=run_id
                        )
                    # Auto-extend CODER scope based on files mentioned in acceptance criteria.
                    # This prevents the common Planner-Coder mismatch where a criterion like
                    # "style.css linked from index.html" forces the CODER to modify index.html
                    # even though it's not in expected_artifacts.
                    if task.assigned_role == "CODER":
                        try:
                            assignment_payload["task_definition"] = _extend_scope_from_criteria(
                                assignment_payload["task_definition"], run_id
                            )
                        except Exception as exc:
                            logger.warning(
                                "[Scheduler] Failed to extend scope for %s: %s", task.id, exc
                            )
                    asyncio.create_task(self.messenger_callback(assignment_payload))
                else:
                    logger.warning("No messenger callback provided. Assignment sent to vacuum.")
            else:
                logger.warning(f"Failed to assign task {task.id} (already claimed?)")
        
        # Summary: one line per meaningful change, not per tick.
        # Always log assignments (they are events).
        # Only log delays if the blocking set actually changed.
        if assigned_this_tick:
            parts = [f"assigned: {', '.join(assigned_this_tick)}"]
            if delayed_this_tick:
                delayed_str = "; ".join(f"{tid} ({reason})" for tid, reason in delayed_this_tick)
                parts.append(f"delayed: {delayed_str}")
            logger.info(f"[Scheduler] Tick: {'; '.join(parts)}")
        elif delayed_this_tick:
            # Only log if the set of blocked tasks changed since last tick.
            current_delay_signature = tuple(sorted(delayed_this_tick))
            if current_delay_signature != last_delay_signature:
                delayed_str = "; ".join(f"{tid} ({reason})" for tid, reason in delayed_this_tick)
                logger.info(f"[Scheduler] Tick: delayed: {delayed_str}")
                self._last_delay_signature = current_delay_signature
