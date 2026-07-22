import logging
import asyncio
import uuid
import shutil
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from sqlalchemy import select, update
from engine.db import DatabaseManager
from engine.models import Run, Project, Plan, Task, RunStatus
from engine.orchestrator import Orchestrator
from engine.repository import MessageRepository
from engine.services.narrator import Narrator
from engine.session_registry import SessionRegistry

logger = logging.getLogger(__name__)

class RunController:
    """
    The Supervisor of the Firma Platform.
    Responsible for the lifecycle of Runs: Creation, Start, Stop, and Monitoring.
    
    DESIGN RULE: The Controller is a Lifecycle Manager. 
    It manages Orchestrators, but it DOES NOT manage Tasks or Business Logic.
    """
    def __init__(self, db_manager: DatabaseManager, 
                 scheduler_factory, 
                 transport_factory, 
                 execution_service, 
                 sandbox):
        self.db = db_manager
        self.scheduler_factory = scheduler_factory
        self.transport_factory = transport_factory
        self.execution_service = execution_service
        self.sandbox = sandbox
        
        # active_runs: Maps run_id -> Orchestrator instance
        self._orchestrators: Dict[str, Orchestrator] = {}
        # running_tasks: Maps run_id -> asyncio.Task (the run_forever loop)
        self._running_tasks: Dict[str, asyncio.Task] = {}

    async def create_run(self, config: Dict[str, Any]) -> str:
        """
        Bootstraps a new isolated run from a configuration.
        Sequence: Run -> Project -> Plan -> Task
        """
        async with self.db.session_scope() as session:
            # 1. Create Run
            run = Run(
                id=str(uuid.uuid4()),
                status="ACTIVE",
                config_json=config,
                created_at=datetime.now(timezone.utc)
            )
            session.add(run)
            await session.flush()
            run_id = run.id

            Narrator.run_bootstrapped(run_id, config)

            # 2. Create Project
            project = Project(
                id=str(uuid.uuid4()),
                run_id=run_id,
                name=config.get("project_name", "Unnamed Project"),
                status="ACTIVE"
            )
            session.add(project)
            await session.flush()

            # 3. Create Plan
            plan = Plan(
                id=str(uuid.uuid4()),
                run_id=run_id,
                project_id=project.id,
                version=1,
                name=config.get("plan_name", "Initial Plan"),
                status="IN_PROGRESS"
            )
            session.add(plan)
            await session.flush()

            # Bind active plan to project
            project.active_plan_id = plan.id

            # 4. Create Initial Tasks (Bootstrap)
            # Phase 3 (Idee B): RESEARCHER runs as its OWN task BEFORE the PLANNER
            # (clear sequencing). The PLANNER depends on the RESEARCHER completing,
            # so the scheduler won't dispatch planning until the read-only research
            # brief exists. The Researcher is read-only; it must not modify project files.
            researcher_task = Task(
                id=str(uuid.uuid4()),
                run_id=run_id,
                plan_id=plan.id,
                state="READY",
                execution_phase="RESEARCHING",
                assigned_role="RESEARCHER",
                state_revision=0,
                expected_artifacts=[{"path": "research/brief.md", "type": "CREATE"}],
                acceptance_criteria=["EXISTS:research/brief.md"],
                verification_type="research_readonly",
                max_retries=1,
                updated_at=datetime.now(timezone.utc)
            )
            session.add(researcher_task)
            await session.flush()

            task = Task(
                id=str(uuid.uuid4()),
                run_id=run_id,
                plan_id=plan.id,
                state="READY",
                execution_phase="PLANNING",
                assigned_role="PLANNER",
                state_revision=0,
                dependencies=[researcher_task.id],
                expected_artifacts=config.get("expected_artifacts", []),
                acceptance_criteria=config.get("acceptance_criteria", []),
                verification_type=config.get("verification_type", "structural_web"),
                max_retries=1, # Industrial Limit for Planning
                updated_at=datetime.now(timezone.utc)
            )
            
            logger.info(f"[PERSISTENCE DEBUG] Before add: task={task.id}, role={task.assigned_role}")
            session.add(task)
            await session.flush()
            
            # Final verification: reload from DB to see if it's actually there
            from sqlalchemy import select
            res = await session.execute(select(Task).filter(Task.id == task.id))
            task_db = res.scalars().first()
            
            logger.info(f"Run {run_id} bootstrapped successfully.")
            return run_id

    async def start_run(self, run_id: str, messenger_callback=None):
        """
        Instantiates and starts the Orchestrator for a specific run.
        `messenger_callback` (optional) ueberschreibt den Default (transport.dispatch).
        Wird im PiMesh-Modus genutzt, um dispatch + PiProvider-Spawn zu koppeln
        (single authority: Scheduler nach READY->CLAIMED).
        """
        if run_id in self._orchestrators:
            logger.warning(f"Run {run_id} is already running.")
            return

        Narrator.run_started(run_id)

        # 1. Create Runtime Components
        # Use factories to ensure fresh instances per run
        transport = self.transport_factory()
        scheduler = self.scheduler_factory(self.db, messenger_callback=messenger_callback or transport.dispatch)
        
        orchestrator = Orchestrator(
            db_manager=self.db,
            scheduler=scheduler,
            transport=transport,
            execution_service=self.execution_service,
            sandbox=self.sandbox,
            run_id=run_id
        )

        # 2. Update Run status to started
        async with self.db.session_scope() as session:
            await session.execute(
                update(Run)
                .where(Run.id == run_id)
                .values(started_at=datetime.now(timezone.utc))
            )

        # 3. Start the loop
        orchestrator.running = True
        task = asyncio.create_task(orchestrator.run_forever())
        
        self._orchestrators[run_id] = orchestrator
        self._running_tasks[run_id] = task
        
        logger.info(f"Orchestrator for run {run_id} is now active.")

    async def stop_run(self, run_id: str):
        """
        Graceful stop: Signals the orchestrator to stop and waits for loop completion.
        """
        logger.info(f"Stopping run {run_id} gracefully...")
        orchestrator = self._orchestrators.get(run_id)
        if not orchestrator:
            logger.warning(f"No active orchestrator found for run {run_id}.")
            return

        await orchestrator.stop()
        
        # Wait for the task to finish
        task = self._running_tasks.get(run_id)
        if task:
            try:
                await asyncio.wait_for(task, timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning(f"Run {run_id} did not stop gracefully. Forcing cancellation.")
                task.cancel()

        # Cleanup. WICHTIG: Den Run-Status hier NICHT ueberschreiben -- er wurde
        # bereits korrekt gesetzt (von _check_run_completion -> COMPLETED/FAILED, oder
        # vom Guardian-Fail-Fast). Ein hartes status="COMPLETED" wuerde einen
        # fehlgeschlagenen Run faelschlich als COMPLETED melden (Bug A).
        self._orchestrators.pop(run_id, None)
        self._running_tasks.pop(run_id, None)
        SessionRegistry.cleanup_run(run_id)

        async with self.db.session_scope() as session:
            result = await session.execute(select(Run).where(Run.id == run_id))
            run = result.scalars().first()
            status = run.status if run else "UNKNOWN"
            # completed_at nur nachtragen, falls noch leer (terminaler Run).
            if run and run.status in ("COMPLETED", "FAILED", "CANCELLED") and run.completed_at is None:
                await session.execute(
                    update(Run)
                    .where(Run.id == run_id)
                    .values(completed_at=datetime.now(timezone.utc))
                )
        Narrator.run_stopped(run_id, status)

    async def cancel_run(self, run_id: str):
        """
        Hard stop: Marks run as CANCELLED and terminates orchestrator immediately.
        """
        logger.info(f"Cancelling run {run_id}...")
        
        # 1. Mark in DB first (Orchestrator tick check will catch this)
        async with self.db.session_scope() as session:
            await session.execute(
                update(Run)
                .where(Run.id == run_id)
                .values(
                    status="CANCELLED",
                    completed_at=datetime.now(timezone.utc)
                )
            )

        # 2. Signal orchestrator
        orchestrator = self._orchestrators.get(run_id)
        if orchestrator:
            orchestrator.stop()
        
        # 3. Cancel the async task
        task = self._running_tasks.get(run_id)
        if task:
            task.cancel()

        self._orchestrators.pop(run_id, None)
        self._running_tasks.pop(run_id, None)
        SessionRegistry.cleanup_run(run_id)
        
        logger.info(f"Run {run_id} cancelled and terminated.")

    async def get_run_status(self, run_id: str) -> Dict[str, Any]:
        """
        Aggregates status and metrics for a specific run.
        """
        async with self.db.session_scope() as session:
            result = await session.execute(select(Run).filter(Run.id == run_id))
            run = result.scalars().first()
            if not run:
                return {"error": "Run not found"}
            
            return {
                "run_id": run.id,
                "status": run.status,
                "created_at": run.created_at.isoformat() if run.created_at else None,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "metrics": run.metrics_json or {},
                "failure_reason": run.failure_reason
            }

    async def get_run_summary(self, run_id: str) -> Dict[str, Any]:
        """
        Schlanker v1 Run-Summary fuer das Archiv (Run-Record + Task-States +
        failure_reason + Summary-Counters). Keine vollen Transition-Events.
        """
        async with self.db.session_scope() as session:
            run_res = await session.execute(select(Run).filter(Run.id == run_id))
            run = run_res.scalars().first()
            if not run:
                return {}

            tasks_res = await session.execute(select(Task).filter(Task.run_id == run_id))
            tasks = tasks_res.scalars().all()

            task_summary = []
            counters = {"total": 0, "done": 0, "failed": 0, "review_feedback": 0}
            for t in tasks:
                counters["total"] += 1
                if t.state == "DONE":
                    counters["done"] += 1
                if t.state in ("FAILED", "FAILED_ITERATION_LIMIT"):
                    counters["failed"] += 1
                has_feedback = bool(t.last_review_feedback)
                if has_feedback:
                    counters["review_feedback"] += 1
                task_summary.append({
                    "task_id": t.id,
                    "role": t.assigned_role,
                    "state": t.state,
                    "execution_phase": t.execution_phase,
                    "review": t.last_review_feedback if has_feedback else None,
                })

            return {
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "terminal_state": run.status,
                "task_summary": task_summary,
                "failure_reason": run.failure_reason,
                "summary_counters": counters,
            }

    async def cleanup_runs(self, retention_count: int = 10):
        """
        Maintenance task: Removes old runs and their associated artifacts.
        Protects runs marked as is_milestone=True.
        """
        logger.info(f"Starting maintenance: cleaning up runs with retention={retention_count}")
        
        from engine.settings import ARTIFACT_DIR

        async with self.db.session_scope() as session:
            # 1. Find all non-milestone runs, sorted by creation date (newest first)
            result = await session.execute(
                select(Run)
                .filter(Run.is_milestone == False)
                .order_by(Run.created_at.desc())
            )
            all_runs = result.scalars().all()
            
            if len(all_runs) <= retention_count:
                logger.info("No runs to clean up.")
                return 0

            runs_to_delete = all_runs[retention_count:]
            deleted_count = 0

            for run in runs_to_delete:
                # A. Delete physical artifacts
                # We need to find all artifacts associated with this run
                from engine.models import Artifact
                art_result = await session.execute(
                    select(Artifact).filter(Artifact.task_id.in_(
                        select(Task.id).filter(Task.run_id == run.id)
                    ))
                )
                artifacts = art_result.scalars().all()
                
                for art in artifacts:
                    art_path = Path(art.storage_path)
                    if art_path.exists():
                        await asyncio.to_thread(art_path.unlink)
                
                # Also try to clean up the run's directory in artifact_store
                # Since we now use data/artifacts/<run_id>, we can just delete the run folder
                run_dir = ARTIFACT_DIR / run.id
                if run_dir.exists():
                    await asyncio.to_thread(shutil.rmtree, run_dir)

                # B. Delete from DB (Cascade should handle Project, Plan, Task)
                await session.delete(run)
                deleted_count += 1
            
            await session.commit()
            logger.info(f"Cleanup complete. Removed {deleted_count} old runs and their artifacts.")
            return deleted_count
