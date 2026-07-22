import logging
import time
import asyncio
from typing import List
from engine.repository import MessageRepository
from engine.models import Message, MessageType, Task, MessageHeader, Run

logger = logging.getLogger(__name__)

class Scheduler:
    """
    Minimalist Deterministic Scheduler (v0).
    Responsible for the 'Impulse' of the engine.
    """

    def __init__(self, db_manager, messenger_callback=None):
        self.db = db_manager
        self.messenger_callback = messenger_callback
        self.ack_timeout = 600  # Raised to provider max (600s) + governance buffer

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

        logger.info(f"Found {len(ready_tasks)} tasks ready for assignment on plan {active_plan_id} (run {run_id}).")

        for task in ready_tasks:
            if task.run_id != run_id:
                continue

            # FIX: Passing run_id to assign_task_with_timeout
            success = await repo.assign_task_with_timeout(session, run_id, task.id, self.ack_timeout)
            if success:
                logger.info(f"Task {task.id} assigned. Sending TASK_ASSIGNMENT.")
                
                if self.messenger_callback:
                    logger.info(f"[Scheduler] About to dispatch task {task.id}")
                    prev_fb = getattr(task, "last_review_feedback", None)
                    if prev_fb:
                        logger.info(f"[Collaborative] CODER retry for {task.id} carries previous feedback")
                    assignment_payload = {
                        "event": "TASK_ASSIGNMENT",
                        "run_id": run_id,
                        "task_id": task.id, 
                        "role": task.assigned_role,
                        "state_revision": task.state_revision,
                        "prompt": project_prompt,
                        "task_definition": {
                            "description": task.description,
                            "acceptance_criteria": task.acceptance_criteria,
                            "previous_feedback": prev_fb
                        }
                    }
                    # Phase 3 (Idee B): ground the PLANNER on the Researcher's read-only
                    # briefing. Handoff strictly via workspace file (no P2P). CODER tasks
                    # created by the plan inherit the same briefing pointer below.
                    if task.assigned_role == "PLANNER":
                        assignment_payload.setdefault("task_definition", {})["research_brief"] = "research/brief.md"
                        assignment_payload["prompt"] = (
                            f"{project_prompt}\n\n[Research context] A read-only briefing from the "
                            f"Researcher is available at workspace/{run_id}/research/brief.md — "
                            f"ground your plan on it."
                        )
                    asyncio.create_task(self.messenger_callback(assignment_payload))
                else:
                    logger.warning("No messenger callback provided. Assignment sent to vacuum.")
            else:
                logger.warning(f"Failed to assign task {task.id} (already claimed?)")
