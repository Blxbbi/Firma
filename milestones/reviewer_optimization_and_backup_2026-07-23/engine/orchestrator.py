import logging
import asyncio
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
from sqlalchemy import select
from engine.db import DatabaseManager
from engine.services.execution import ExecutionService
from engine.services.sandbox import LocalPythonSandbox
from engine.services.guardian import GuardianPipeline
from engine.services.artifact_store import ArtifactStore
from engine.services.narrator import Narrator
from engine.transport.base import WorkerTransport
from engine.models import Run

logger = logging.getLogger(__name__)

class Orchestrator:
    """
    The Heartbeat of Firma.
    Coordinates the flow between Scheduler and Execution using strict session isolation.
    """
    def __init__(self, db_manager: DatabaseManager, scheduler, transport: WorkerTransport, execution_service: ExecutionService, sandbox: LocalPythonSandbox, run_id: str):
        self.db = db_manager
        self.scheduler = scheduler
        self.transport = transport
        self.execution_service = execution_service
        self.sandbox = sandbox
        self.run_id = run_id
        self.guardian = GuardianPipeline(ArtifactStore())
        self.running = False
        self._timeout_latches = set() # Tracks (task_id, state_revision) to prevent timeout storms
        self._task_locks: Dict[str, asyncio.Lock] = {} # Per-task serialization to prevent event races
        self._slow_log_timestamps: Dict[str, datetime] = {} # Tracks last "SLOW" log emission per task

    async def tick(self):
        """
        A single cycle of the engine.
        """
        # Run Lifecycle Guard: Stop if the run is no longer ACTIVE
        async with self.db.session_scope() as session:
            run_res = await session.execute(select(Run).filter(Run.id == self.run_id))
            run = run_res.scalars().first()
            if not run or run.status != "ACTIVE":
                logger.info(f"Run {self.run_id} is not ACTIVE (status: {run.status if run else 'NOT_FOUND'}). Stopping engine tick.")
                self.running = False
                return

        try:
            # 0. System Phase: Automatic Maintenance
            await self._handle_worker_timeouts()
            await self._handle_verification_phase()

            # 1. Scheduler Phase: Assign READY tasks to Workers
            await self.scheduler.run_tick(self.run_id)

            # 2. Transport Phase: Poll for Worker Responses
            messages = await self.transport.poll()
            
            # 3. Intake Phase: Process responses through the Guardian
            for msg in messages:
                msg_id = msg.envelope.get("message_id")
                payload = msg.envelope.get("payload", {})
                task_id = payload.get("task_id")
                
                if not task_id:
                    logger.warning(f"Message {msg_id} missing task_id. Skipping.")
                    await msg.ack()
                    continue

                Narrator.worker_response(task_id, payload.get("event", "UNKNOWN"), payload.get("sender_role", "UNKNOWN"), self.run_id)
                
                lock = self._task_locks.setdefault(task_id, asyncio.Lock())
                
                async def process_serialized(m=msg, tid=task_id, mid=msg_id):
                    async with lock:
                        try:
                            async with self.db.session_scope() as session:
                                data = m.envelope.copy()
                                while "payload" in data and isinstance(data["payload"], dict):
                                    payload = data.pop("payload")
                                    data.update(payload)
                                
                                business_payload = {
                                    "message_id": data.get("message_id") or m.envelope.get("message_id"),
                                    "timestamp": data.get("timestamp") or m.envelope.get("timestamp"),
                                    "protocol_version": data.get("protocol_version", "1.0"),
                                    "event": data.get("event"),
                                    "sender_role": data.get("sender_role"),
                                    "state_revision": data.get("state_revision"),
                                    **data,
                                }
                                
                                success, reason = await self.guardian.process_response(session, business_payload, run_id=self.run_id)
                                if not success and reason != "ALREADY_PROCESSED":
                                    logger.warning(f"Guardian rejected worker response {mid}: {reason}")
                        except Exception as e:
                            logger.error(f"Critical failure in Guardian intake for {tid}: {str(e)}")
                        finally:
                            await m.ack()

                asyncio.create_task(process_serialized())
            
            # 4. Completion Phase: Check if all tasks are finished
            await self._check_run_completion()

        except Exception as e:
            logger.exception(f"Orchestrator tick encountered a critical error: {str(e)}")

    async def run_forever(self):
        """
        Continuous execution loop.
        """
        self.running = True
        logger.info("Orchestrator heartbeat started.")
        while self.running:
            await self.tick()
            await asyncio.sleep(0.5)

    async def stop(self):
        """
        Stops the orchestrator loop.
        """
        self.running = False

    async def _handle_verification_phase(self):
        """
        Triggers the deterministic execution of tasks in the VERIFYING phase.
        Only triggers if the task is explicitly in ExecutionPhase.VERIFYING.
        """
        import uuid
        from datetime import datetime, timezone
        from engine.models import Plan, ExecutionPhase
        async with self.db.session_scope() as session:
            from engine.repository import MessageRepository
            repo = MessageRepository()
            tasks_to_verify = await repo.get_tasks_by_role(session, self.run_id, "SYSTEM")
            
            for task in tasks_to_verify:
                # STRICT GUARD: Only verify if we are actually in the VERIFYING phase.
                # This prevents loops when a task is moved back to CODING but still has SYSTEM role.
                if task.execution_phase != ExecutionPhase.VERIFYING.value:
                    logger.debug(f"[Orchestrator] Task {task.id} has SYSTEM role but is in phase {task.execution_phase}. Skipping verification.")
                    continue

                Narrator.system_action("Triggering sandbox verification", task_id=task.id)
                
                plan_result = await session.execute(select(Plan).filter(Plan.id == task.plan_id, Plan.run_id == self.run_id))
                plan = plan_result.scalars().first()
                if not plan:
                    logger.error(f"Plan {task.plan_id} not found for task {task.id} in run {self.run_id}. Skipping.")
                    continue
                
                event, logs = await self.execution_service.verify(
                    session, 
                    task_id=task.id, 
                    project_id=plan.project_id, 
                    plan_version=plan.version,
                    run_id=self.run_id,
                    verification_type=task.verification_type or "structural_web"
                )
                
                system_response = {
                    "protocol_version": "1.0",
                    "message_id": f"sys-{uuid.uuid4()}",
                    "run_id": self.run_id,
                    "task_id": task.id,
                    "state_revision": task.state_revision,
                    "event": event.value,
                    "sender_role": "SYSTEM",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "artifacts": {},
                    "logs": logs,
                }
                
                lock = self._task_locks.setdefault(task.id, asyncio.Lock())
                async with lock:
                    success, reason = await self.guardian.process_response(session, system_response, run_id=self.run_id)
                
                if not success:
                    logger.error(f"Guardian rejected SYSTEM verification for {task.id}: {reason}")
                else:
                    Narrator.transition(task.id, "VERIFYING", "CODING" if event.value == "VERIFY_FAILURE" else "COMPLETE", event.value)

    async def _check_run_completion(self):
        """
        Checks if all tasks for the current run have reached a terminal state.
        If so, marks the run as COMPLETED or FAILED.
        """
        from engine.models import Task, Run
        from sqlalchemy import update, func

        async with self.db.session_scope() as session:
            # 1. Count tasks that are NOT in a terminal state
            # Terminal states: COMPLETE, FAILED, FAILED_ITERATION_LIMIT
            terminal_phases = {"COMPLETE", "FAILED", "FAILED_ITERATION_LIMIT"}
            
            result = await session.execute(
                select(func.count(Task.id)).filter(
                    Task.run_id == self.run_id,
                    ~Task.execution_phase.in_(terminal_phases)
                )
            )
            remaining_count = result.scalar()

            if remaining_count > 0:
                return

            Narrator.system_action("All tasks finished. Determining final run status.")

            # 2. Check if any task failed
            failure_result = await session.execute(
                select(func.count(Task.id)).filter(
                    Task.run_id == self.run_id,
                    Task.execution_phase.in_({"FAILED", "FAILED_ITERATION_LIMIT"})
                )
            )
            failed_count = failure_result.scalar()

            final_status = "FAILED" if failed_count > 0 else "COMPLETED"
            values = {"status": final_status, "completed_at": datetime.now(timezone.utc)}
            if failed_count > 0:
                # failure_reason aus den fehlgeschlagenen Tasks ableiten
                # (der Guardian markiert den Run nicht mehr sofort -> hier zentral).
                failed_tasks = await session.execute(
                    select(Task).filter(
                        Task.run_id == self.run_id,
                        Task.execution_phase.in_({"FAILED", "FAILED_ITERATION_LIMIT"})
                    )
                )
                failed_ids = [t.id for t in failed_tasks.scalars().all()]
                values["failure_reason"] = f"{failed_count} task(s) failed: " + ", ".join(failed_ids)

            await session.execute(
                update(Run)
                .where(Run.id == self.run_id)
                .values(**values)
            )
            
            Narrator.run_stopped(self.run_id, final_status)

    def _normalize_utc(self, dt):
        """Ensures datetime objects are offset-aware UTC."""
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    async def _handle_worker_timeouts(self):
        """
        Detects tasks stuck in CLAIMED state.
        """
        from engine.models import Task, TaskEvent, AssignedRole
        import uuid
        from sqlalchemy import select
        from engine.repository import MessageRepository
        
        # Synchronized with Scheduler's ack_timeout (600s provider max + buffer)
        SOFT_TIMEOUT_THRESHOLD = timedelta(seconds=120)
        HARD_TIMEOUT_THRESHOLD = timedelta(seconds=600)
        now = datetime.now(timezone.utc)
        
        async with self.db.session_scope() as session:
            repo = MessageRepository()
            # We now get ALL claimed tasks to provide "SLOW" telemetry
            stuck_tasks = await repo.get_claimed_tasks(session, self.run_id)

            for task in stuck_tasks:
                task_ts = self._normalize_utc(task.updated_at)
                diff = now - task_ts
                
                if diff > HARD_TIMEOUT_THRESHOLD:
                    latch_key = (task.id, task.state_revision)
                    if latch_key in self._timeout_latches:
                        continue
                    
                    Narrator.system_action("HARD TIMEOUT detected", task_id=task.id, details=f"elapsed {diff.seconds}s")
                    timeout_response = {
                        "protocol_version": "1.0",
                        "message_id": f"sys-timeout-{uuid.uuid4()}",
                        "run_id": self.run_id,
                        "task_id": task.id,
                        "state_revision": task.state_revision,
                        "event": TaskEvent.WORKER_TIMEOUT.value,
                        "sender_role": AssignedRole.SYSTEM.value,
                        "timestamp": now.isoformat(),
                        "artifacts": {},
                        "logs": f"Worker failed to submit result within hard timeout of {HARD_TIMEOUT_THRESHOLD.seconds}s.",
                    }
                    
                    self._timeout_latches.add(latch_key)
                    
                    lock = self._task_locks.setdefault(task.id, asyncio.Lock())
                    async with lock:
                        success, reason = await self.guardian.process_response(session, timeout_response, run_id=self.run_id)
                    
                    if not success:
                        logger.error(f"Guardian rejected HARD TIMEOUT for {task.id}: {reason}")
                    else:
                        logger.info(f"Task {task.id} successfully recovered from hard timeout.")

                elif diff > SOFT_TIMEOUT_THRESHOLD:
                    last_log = self._slow_log_timestamps.get(task.id)
                    if last_log is None or (now - last_log).total_seconds() >= 30:
                        Narrator.slow_warning(task.id, diff.seconds)
                        self._slow_log_timestamps[task.id] = now
            
            current_claimed_keys = {
                (t.id, t.state_revision) for t in stuck_tasks 
                if t.state == "CLAIMED"
            }
