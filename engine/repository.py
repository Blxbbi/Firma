from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update, select
from .models import Project, Plan, Task, Artifact, MessageLog, TaskEventLog, SubmissionLog, SubmissionOutcome
import uuid
from datetime import datetime, timezone
import logging
import time
from typing import List, Optional
from engine.services.telemetry import telemetry

logger = logging.getLogger(__name__)

# --- State Transition Guard ---
VALID_TRANSITIONS = {
    "BLOCKED": ["READY", "CANCELLED", "FAILED"],
    "READY": ["CLAIMED", "CANCELLED", "FAILED"],
    "CLAIMED": ["IN_PROGRESS", "CANCELLED", "FAILED"],
    "IN_PROGRESS": ["SUBMITTED", "CANCELLED", "FAILED"],
    "SUBMITTED": ["VERIFIED", "READY", "CANCELLED", "FAILED"],
    "VERIFIED": [], # Terminal state
    "FAILED": [],   # Terminal state
    "CANCELLED": [], # Terminal state
}

class MessageRepository:
    """
    The real repository implementing the deterministic persistence layer.
    Fully Asynchronous.
    
    DESIGN RULES:
    1. Stateless: All methods receive the session as an argument.
    2. Run-Isolated: ALL accesses MUST be scoped by run_id to prevent cross-run leakage.
    3. No Implicit State: No automatic plan activation or versioning.
    """
    def __init__(self, db_session: AsyncSession = None, artifact_store_root: str = None):
        self.db = db_session 
        self.artifact_store_root = artifact_store_root

    # --- Project & Plan Reading ---

    async def get_project(self, session: AsyncSession, run_id: str, project_id: str) -> Optional[Project]:
        """Fetches a project by its ID, ensuring it belongs to the run."""
        t0 = time.perf_counter_ns()
        result = await session.execute(select(Project).filter(Project.id == project_id, Project.run_id == run_id))
        telemetry.observe("db_select_latency_ns", time.perf_counter_ns() - t0)
        return result.scalars().first()

    async def get_active_plan(self, session: AsyncSession, run_id: str, project_id: str) -> Optional[Plan]:
        """
        Fetches the plan currently being executed (active_plan_id) for a run.
        """
        project = await self.get_project(session, run_id, project_id)
        if not project or not project.active_plan_id:
            return None
        result = await session.execute(select(Plan).filter(Plan.id == project.active_plan_id, Plan.run_id == run_id))
        return result.scalars().first()

    async def get_current_plan(self, session: AsyncSession, run_id: str, project_id: str) -> Optional[Plan]:
        """
        Fetches the last stable completed plan (current_plan_id) for a run.
        """
        project = await self.get_project(session, run_id, project_id)
        if not project or not project.current_plan_id:
            return None
        result = await session.execute(select(Plan).filter(Plan.id == project.current_plan_id, Plan.run_id == run_id))
        return result.scalars().first()

    async def get_plan(self, session: AsyncSession, run_id: str, project_id: str, plan_id: str) -> Optional[Plan]:
        """
        Fetches a specific plan version, ensuring it belongs to the project and run.
        """
        t0 = time.perf_counter_ns()
        result = await session.execute(select(Plan).filter(
            Plan.id == plan_id, 
            Plan.project_id == project_id,
            Plan.run_id == run_id
        ))
        telemetry.observe("db_select_latency_ns", time.perf_counter_ns() - t0)
        return result.scalars().first()

    async def get_task_by_id(self, session: AsyncSession, run_id: str, task_id: str) -> Optional[Task]:
        """Fetches a task by its ID, ensuring it belongs to the run."""
        t0 = time.perf_counter_ns()
        result = await session.execute(select(Task).filter(Task.id == task_id, Task.run_id == run_id))
        telemetry.observe("db_select_latency_ns", time.perf_counter_ns() - t0)
        return result.scalars().first()

    # --- Task Reading ---

    async def get_task(self, session: AsyncSession, run_id: str, project_id: str, plan_id: str, task_id: str) -> Optional[Task]:
        """
        Fetches a task, ensuring it belongs to the specific plan, project and run.
        """
        plan = await self.get_plan(session, run_id, project_id, plan_id)
        if not plan:
            return None
        
        result = await session.execute(select(Task).filter(
            Task.id == task_id,
            Task.plan_id == plan_id,
            Task.run_id == run_id
        ))
        return result.scalars().first()

    async def get_tasks_for_plan(self, session: AsyncSession, run_id: str, project_id: str, plan_id: str) -> List[Task]:
        """Fetches all tasks for a given plan version, scoped by run."""
        plan = await self.get_plan(session, run_id, project_id, plan_id)
        if not plan:
            return []
        result = await session.execute(select(Task).filter(Task.plan_id == plan_id, Task.run_id == run_id))
        return list(result.scalars().all())

    async def get_unassigned_ready_tasks_for_project(self, session: AsyncSession, run_id: str, project_id: str) -> List[Task]:
        """
        Returns tasks that are READY and unassigned for the current active plan of a run.
        """
        active_plan = await self.get_active_plan(session, run_id, project_id)
        if not active_plan:
            return []
            
        result = await session.execute(select(Task).filter(
            Task.plan_id == active_plan.id,
            Task.state == 'READY',
            Task.assigned_worker == None,
            Task.run_id == run_id
        ))
        return list(result.scalars().all())

    async def get_submitted_tasks_for_project(self, session: AsyncSession, run_id: str, project_id: str) -> List[Task]:
        """Returns tasks in SUBMITTED state for the active plan of the project in a run."""
        active_plan = await self.get_active_plan(session, run_id, project_id)
        if not active_plan:
            return []
            
        result = await session.execute(select(Task).filter(
            Task.plan_id == active_plan.id,
            Task.state == 'SUBMITTED',
            Task.run_id == run_id
        ))
        return list(result.scalars().all())

    # --- Artifact Reading ---

    async def get_artifacts_for_plan(self, session: AsyncSession, run_id: str, project_id: str, plan_id: str) -> List[Artifact]:
        """
        Fetches all artifacts for a given plan in a run.
        Returns only the latest version per (task_id, path).
        Semantics: task-local artifacts. Tasks are independent workspaces;
        two tasks may produce files with the same relative path (e.g. style.css)
        without overwriting each other.
        """
        result = await session.execute(select(Task.id).filter(Task.plan_id == plan_id, Task.run_id == run_id))
        task_ids = result.scalars().all()
        
        if not task_ids:
            return []

        result = await session.execute(select(Artifact).filter(
            Artifact.task_id.in_(task_ids)
        ))
        all_artifacts = result.scalars().all()
        
        latest = {}
        for art in all_artifacts:
            key = (art.task_id, art.path)
            if key not in latest or art.version > latest[key].version:
                latest[key] = art
                
        return list(latest.values())

    # --- Artifact Management ---

    async def save_artifact(self, session: AsyncSession, run_id: str, project_id: str, task_id: str, path: str, storage_path: str, file_hash: str = "UNKNOWN") -> bool:
        """
        Persists artifact metadata to the database.
        """
        from pathlib import Path
        
        project = await self.get_project(session, run_id, project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found in run {run_id}")
        if not project.active_plan_id:
            raise ValueError(f"Project {project_id} has no active plan")

        active_plan = await self.get_plan(session, run_id, project_id, project.active_plan_id)
        if not active_plan:
            raise ValueError(f"Active plan {project.active_plan_id} not found in run {run_id}")
        if active_plan.status != "IN_PROGRESS":
            raise ValueError(f"Active plan {active_plan.id} is not IN_PROGRESS (status: {active_plan.status})")

        if not self.artifact_store_root:
            raise ValueError("Repository artifact_store_root is not configured")

        try:
            artifact_root = Path(self.artifact_store_root).resolve()
            actual_path = Path(storage_path).resolve()
            # Use the project's run_id to define the current root, as a project can move between plans
            # but always stays within the run.
            expected_root = (artifact_root / run_id).resolve()
            
            if not actual_path.is_relative_to(expected_root):
                raise ValueError(f"Storage path {actual_path} is not relative to expected root {expected_root}")
        except Exception as e:
            raise ValueError(f"Path validation failed: {str(e)}")

        # Task Ownership Validation
        result = await session.execute(select(Task).filter(
            Task.id == task_id,
            Task.plan_id == active_plan.id,
            Task.run_id == run_id
        ))
        task = result.scalars().first()
        if not task:
            raise ValueError(f"Task {task_id} not found or does not belong to active plan {active_plan.id} in run {run_id}")

        # Meta-data persistence
        t0 = time.perf_counter_ns()
        result = await session.execute(select(Artifact).filter(
            Artifact.task_id == task_id, 
            Artifact.path == path
        ))
        existing = result.scalars().first()
        
        if existing:
            existing.storage_path = storage_path
            existing.hash = file_hash
            existing.version += 1
        else:
            new_art = Artifact(
                task_id=task_id,
                path=path,
                hash=file_hash,
                storage_path=storage_path
            )
            session.add(new_art)
        
        telemetry.observe("db_write_latency_ns", time.perf_counter_ns() - t0)
        return True

    # --- Idempotency & Logging ---

    async def is_message_processed(self, session: AsyncSession, run_id: str, message_id: str) -> bool:
        result = await session.execute(select(MessageLog).filter(MessageLog.message_id == message_id, MessageLog.run_id == run_id))
        exists = result.scalars().first()
        return exists is not None

    async def mark_message_processed(self, session: AsyncSession, run_id: str, message_id: str, plan_id: str, task_id: str, sender: str, recipient: str, msg_type: str, error_reason: Optional[str] = None) -> None:
        """
        Records that a message has been processed. 
        """
        from .models import ProcessedEvent, MessageLog
        t0 = time.perf_counter_ns()
        
        event = ProcessedEvent(
            message_id=message_id,
            task_id=task_id,
            revision=0,
            timestamp=datetime.now(timezone.utc)
        )
        session.add(event)
        
        log = MessageLog(
            message_id=message_id,
            run_id=run_id,
            plan_id=plan_id,
            task_id=task_id,
            sender=sender,
            recipient=recipient,
            message_type=msg_type,
            type_version=1,
            received_at=datetime.now(timezone.utc),
            processing_status="PROCESSED" if not error_reason else "REJECTED",
            error_reason=error_reason
        )
        session.add(log)
        
        telemetry.observe("db_write_latency_ns", time.perf_counter_ns() - t0)

    async def save_submission_log(self, session: AsyncSession, run_id: str, log_entry: SubmissionLog) -> bool:
        """
        Persists a worker submission attempt to the SubmissionLog.
        """
        t0 = time.perf_counter_ns()
        try:
            log_entry.run_id = run_id
            session.add(log_entry)
            telemetry.observe("db_write_latency_ns", time.perf_counter_ns() - t0)
            return True
        except Exception as e:
            logger.error(f"Failed to save submission log: {str(e)}")
            return False

    async def get_last_message_for_task(self, session: AsyncSession, run_id: str, project_id: str, plan_id: str, task_id: str) -> Optional[MessageLog]:
        """Fetches the most recent message for a task, scoped by run."""
        task = await self.get_task(session, run_id, project_id, plan_id, task_id)
        if not task:
            return None
            
        result = await session.execute(
            select(MessageLog).filter(MessageLog.task_id == task_id, MessageLog.run_id == run_id).order_by(MessageLog.received_at.desc())
        )
        return result.scalars().first()

    # --- Plan Lifecycle ---

    async def create_plan_version(self, session: AsyncSession, run_id: str, project_id: str, name: str) -> Plan:
        """
        Creates a new immutable plan version for a project in a run.
        """
        project = await self.get_project(session, run_id, project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found in run {run_id}.")

        result = await session.execute(select(Plan).filter(Plan.project_id == project_id, Plan.run_id == run_id).order_by(Plan.version.desc()))
        last_plan = result.scalars().first()
        next_version = (last_plan.version + 1) if last_plan else 1

        new_plan = Plan(
            id=str(uuid.uuid4()),
            run_id=run_id,
            project_id=project_id,
            version=next_version,
            name=name,
            status="PLANNED"
        )
        session.add(new_plan)
        await session.flush()
        return new_plan

    async def activate_plan(self, session: AsyncSession, run_id: str, project_id: str, plan_id: str) -> None:
        """
        Atomically activates a plan for a project in a run.
        """
        project = await self.get_project(session, run_id, project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found in run {run_id}.")

        plan = await self.get_plan(session, run_id, project_id, plan_id)
        if not plan:
            raise ValueError(f"Plan {plan_id} does not belong to project {project_id} in run {run_id}.")

        old_active_id = project.active_plan_id
        if old_active_id and old_active_id != plan_id:
            await self.supersede_plan(session, run_id, project_id, old_active_id)
            await self.cancel_tasks_for_plan(session, run_id, project_id, old_active_id)

        project.active_plan_id = plan_id
        plan.status = "IN_PROGRESS"

    async def supersede_plan(self, session: AsyncSession, run_id: str, project_id: str, plan_id: str) -> None:
        """Marks a plan as superseded in a run."""
        await session.execute(
            update(Plan).filter(Plan.id == plan_id, Plan.project_id == project_id, Plan.run_id == run_id).values(status="SUPERSEDED")
        )

    async def cancel_tasks_for_plan(self, session: AsyncSession, run_id: str, project_id: str, plan_id: str) -> None:
        """
        Explicitly cancels all operational tasks of a plan in a run.
        """
        plan_exists = await session.execute(select(Plan).filter(Plan.id == plan_id, Plan.project_id == project_id, Plan.run_id == run_id))
        if not plan_exists.scalars().first():
            return

        await session.execute(
            update(Task)
            .where(Task.plan_id == plan_id)
            .where(Task.run_id == run_id)
            .where(Task.state.in_(['READY', 'CLAIMED', 'IN_PROGRESS', 'SUBMITTED']))
            .values(state='CANCELLED', updated_at=datetime.now(timezone.utc))
        )

    async def get_tasks_by_role(self, session: AsyncSession, run_id: str, role: str) -> List[Task]:
        result = await session.execute(select(Task).filter(Task.assigned_role == role, Task.run_id == run_id))
        return list(result.scalars().all())

    async def get_unassigned_ready_tasks(self, session: AsyncSession, run_id: str, active_plan_id: str) -> List[Task]:
        now = datetime.now(timezone.utc)
        result = await session.execute(
            select(Task).filter(
                Task.state == 'READY', 
                Task.assigned_worker == None,
                Task.plan_id == active_plan_id,
                Task.run_id == run_id,
                (Task.next_retry_at == None) | (Task.next_retry_at <= now)
            )
        )
        tasks = list(result.scalars().all())
        # Dependency gating: a task is dispatchable only once ALL its dependencies are
        # COMPLETE. If a dependency FAILED, the dependent task is cascade-failed (it can
        # never run). Otherwise it waits for the dependency to finish.
        ready = []
        for t in tasks:
            status = await self._dependency_status(session, run_id, t.dependencies or [])
            if status == "complete":
                ready.append(t)
            elif status == "failed":
                await session.execute(
                    update(Task).where(Task.id == t.id, Task.run_id == run_id).values(
                        execution_phase="FAILED", state="FAILED",
                        updated_at=datetime.now(timezone.utc)
                    )
                )
            # status == "pending": wait for the dependency to finish
        return ready

    async def _dependency_status(self, session: AsyncSession, run_id: str, deps) -> str:
        if not deps:
            return "complete"
        res = await session.execute(
            select(Task.id, Task.execution_phase).filter(Task.id.in_(deps), Task.run_id == run_id)
        )
        by_id = {r.id: r.execution_phase for r in res.all()}
        has_failed = False
        for d in deps:
            phase = by_id.get(d)
            if phase is None:
                return "pending"  # dependency missing -> block
            if phase in ("FAILED", "FAILED_ITERATION_LIMIT"):
                has_failed = True
            elif phase != "COMPLETE":
                return "pending"
        return "failed" if has_failed else "complete"

    async def get_claimed_tasks(self, session: AsyncSession, run_id: str) -> List[Task]:
        """
        Returns all tasks currently in a claimed or processing state for a run.
        Used by the Watchdog to monitor latencies.
        """
        result = await session.execute(select(Task).filter(
            Task.state.in_(['CLAIMED', 'IN_PROGRESS']),
            Task.run_id == run_id
        ))
        return list(result.scalars().all())

    async def get_timed_out_assignments(self, session: AsyncSession, run_id: str) -> List[Task]:
        now = datetime.now(timezone.utc)
        result = await session.execute(select(Task).filter(
            Task.state.in_(['CLAIMED', 'IN_PROGRESS']),
            Task.assignment_timeout < now,
            Task.run_id == run_id
        ))
        return list(result.scalars().all())

    async def reset_task_to_ready(self, session: AsyncSession, run_id: str, task_id: str) -> None:
        await session.execute(
            update(Task).filter(Task.id == task_id, Task.run_id == run_id).values(
                state="READY",
                assigned_worker=None,
                assignment_timeout=None,
                updated_at=datetime.now(timezone.utc)
            )
        )

    async def assign_task_with_timeout(self, session: AsyncSession, run_id: str, task_id: str, timeout_seconds: int) -> bool:
        from datetime import timedelta
        
        result = await session.execute(
            select(
                Task.id, 
                Task.state_revision, 
                Task.execution_phase, 
                Task.assigned_role
            )
            .filter(Task.id == task_id, Task.state == 'READY', Task.run_id == run_id)
        )
        row = result.first()
        if not row:
            return False
            
        # ATOMIC CLAIM: Set state, role, worker, and lease in ONE operation
        success = await self.transition_task_atomic(
            session=session,
            run_id=run_id,
            task_id=row.id,
            expected_revision=row.state_revision,
            new_state='CLAIMED',
            new_phase=row.execution_phase,
            new_role=row.assigned_role, # Preserve the role assigned to this task
            project_id=None, 
            triggering_message_id=f"sched-assign-{uuid.uuid4()}",
            assigned_worker="SYSTEM_SCHEDULER",
            lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=timeout_seconds)
        )
        
        return success

    async def transition_task_atomic(self, session: AsyncSession, run_id: str, task_id: str, expected_revision: int, new_state: str, new_phase: str, project_id: Optional[str] = None, new_role: Optional[str] = None, triggering_message_id: str = None, assigned_worker: Optional[str] = None, lease_expires_at: Optional[datetime] = None) -> bool:
        """
        Atomic Compare-And-Swap (CAS) with Invariant Enforcement.
        """
        active_plan_id = None
        if project_id:
            project = await self.get_project(session, run_id, project_id)
            if not project or not project.active_plan_id:
                return False
            active_plan_id = project.active_plan_id

        # INVARIANT ENFORCEMENT
        # 1. If transitioning to READY, worker MUST be None.
        # We still allow new_role to be set to ensure correct role is assigned for the next claim.
        is_ready_transition = (new_state == "READY")
        
        force_role = new_role
        force_worker = assigned_worker if not is_ready_transition else None

        if force_role is None:
            # Recover role from current state if not explicitly provided
            res = await session.execute(select(Task.assigned_role).filter(Task.id == task_id))
            force_role = res.scalar()
            
        if force_role is None:
            logger.error(f"[Invariant Violation] Attempted transition to {new_state} for task {task_id} but no role is assigned.")
            return False

        stmt = (
            update(Task)
            .where(Task.id == task_id)
            .where(Task.run_id == run_id)
            .where(Task.state_revision == expected_revision)
            .values(
                state=new_state,
                execution_phase=new_phase,
                assigned_role=force_role if force_role is not None else Task.assigned_role,
                state_revision=Task.state_revision + 1,
                assigned_worker=force_worker if not is_ready_transition else None,
                lease_expires_at=lease_expires_at if lease_expires_at is not None else Task.lease_expires_at,
                updated_at=datetime.now(timezone.utc)
            )
        )
        
        if active_plan_id:
            stmt = stmt.where(Task.plan_id == active_plan_id)
        
        t0 = time.perf_counter_ns()
        result = await session.execute(stmt)
        latency = time.perf_counter_ns() - t0
        
        rowcount = result.rowcount
        success = rowcount > 0
        
        telemetry.observe("db_write_latency_ns", latency)
        telemetry.increment("cas_attempts")
        if success:
            telemetry.increment("cas_success")
        else:
            telemetry.increment("cas_conflicts")
            debug_res = await session.execute(select(Task).filter(Task.id == task_id, Task.run_id == run_id))
            actual_task = debug_res.scalars().first()
            if actual_task:
                logger.error(
                    f"[CAS CONFLICT] Task {task_id} (run {run_id}) | Expected Rev: {expected_revision}, "
                    f"Actual Rev: {actual_task.state_revision} | State: {actual_task.state} | "
                    f"Plan: {actual_task.plan_id} (Active: {active_plan_id}) | "
                    f"Trigger: {triggering_message_id}"
                )
        
        if not success:
            return False

        event = TaskEventLog(
            task_id=task_id,
            previous_state=None, 
            new_state=new_state,
            triggering_message_id=triggering_message_id
        )
        session.add(event)
        return True
