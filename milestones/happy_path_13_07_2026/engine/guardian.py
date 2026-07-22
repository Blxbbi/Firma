import logging
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Optional, Tuple
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update as sql_update
from sqlalchemy.orm import joinedload

from engine.models import WorkerResponse, Task, Plan, Project, ProcessedEvent, TaskTransitionLog, ExecutionPhase, TaskEvent, AssignedRole, FileAction, SubmissionOutcome
from engine.governance import GovernanceMatrix, IllegalTransitionError, TransitionResult
from engine.services.artifact_store import ArtifactStore
from engine.services.telemetry import telemetry
from engine.services.narrator import Narrator

logger = logging.getLogger(__name__)

class GuardianError(Exception):
    """Base exception for Guardian pipeline failures."""
    def __init__(self, message: str, error_code: str):
        self.error_code = error_code
        super().__init__(message)

class GuardianPipeline:
    """
    GuardianPipeline: The authoritative intake valve for all worker responses.
    Fully Asynchronous implementation.
    """
    MAX_ITERATIONS = 3

    def __init__(self, artifact_store: ArtifactStore):
        self.artifact_store = artifact_store

    def _normalize_utc(self, dt):
        """Ensures a datetime object is timezone-aware UTC."""
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    async def _log_attempt(self, session: AsyncSession, response: WorkerResponse, task: Task, outcome: SubmissionOutcome, error_code: Optional[str] = None, duration_ms: Optional[int] = None, run_id: Optional[str] = None):
        """
        Strictly observational: Records the outcome of a worker attempt in the SubmissionLog.
        """
        from engine.repository import MessageRepository
        from engine.models import SubmissionLog
        
        repo = MessageRepository()

        model_name = getattr(response, "model_name", "unknown")
        model_version = getattr(response, "model_version", "unknown")
        worker_build = getattr(response, "worker_build_version", "unknown")
        prompt_hash = getattr(response, "prompt_hash", None)
        
        log_entry = SubmissionLog(
            task_id=task.id,
            project_id=task.plan.project_id,
            run_id=run_id,
            revision=task.state_revision,
            message_id=response.message_id,
            worker_id=getattr(response, "worker_id", "unknown"),
            model_name=model_name,
            model_version=model_version,
            worker_build_version=worker_build,
            prompt_hash=prompt_hash,
            artifact_contract_version="1.0",
            outcome=outcome.value,
            error_code=error_code,
            iteration_number=task.attempt_count + 1,
            duration_ms=duration_ms,
            created_at=datetime.now(timezone.utc)
        )

        await repo.save_submission_log(session, run_id, log_entry)
        logger.info(f"[Observability] Logged attempt for {task.id}: {outcome.value} ({error_code or 'OK'})")

    def _validate_artifact_contract(self, response: WorkerResponse) -> Tuple[bool, Optional[str]]:
        """
        Strict validation of the artifact contract.
        Returns (passed, error_code).
        """
        if not response.artifacts:
            return False, "MISSING_ARTIFACTS"

        files = response.artifacts
        if not isinstance(files, list):
            return False, "ARTIFACTS_NOT_A_LIST"
        
        if len(files) == 0:
            return False, "EMPTY_ARTIFACT_LIST"
        
        for idx, item in enumerate(files):
            if not isinstance(item, dict):
                return False, f"ARTIFACT_ITEM_{idx}_NOT_A_DICTIONARY"
            
            for key in ("path", "action"):
                if key not in item:
                    return False, f"ARTIFACT_ITEM_{idx}_MISSING_{key.upper()}"
            
            path = item.get("path")
            action = item.get("action")
            
            if not isinstance(path, str) or not path or path.startswith("/") or ".." in path:
                return False, f"ARTIFACT_ITEM_{idx}_INVALID_PATH"
            
            if action not in [e.value for e in FileAction]:
                return False, f"ARTIFACT_ITEM_{idx}_INVALID_ACTION"
            
            if action in [FileAction.CREATE.value, FileAction.UPDATE.value]:
                if "content" not in item or not isinstance(item.get("content"), str):
                    return False, f"ARTIFACT_ITEM_{idx}_MISSING_OR_INVALID_CONTENT"
            elif action == FileAction.DELETE.value:
                if "content" in item and item.get("content") is not None:
                    return False, f"ARTIFACT_ITEM_{idx}_DELETE_SHOULD_NOT_HAVE_CONTENT"

        return True, None

    async def _evaluate_retry_policy(self, session: AsyncSession, task: Task, event: TaskEvent) -> Tuple[str, ExecutionPhase]:
        """
        Determines if a task should be retried or marked as FAILED based on its retry budget.
        Implements exponential backoff to prevent API hammering.
        Returns (new_state, next_phase).
        """
        # Increment retry count for any failure event
        task.retry_count += 1
        logger.info(f"[Governance] Task {task.id} retry count incremented to {task.retry_count}/{task.max_retries} (Event: {event})")

        if task.retry_count >= self.MAX_ITERATIONS:
            logger.error(f"[Governance] Task {task.id} exhausted retry budget (2). Marking as FAILED.")
            return "FAILED", ExecutionPhase.FAILED
        
        # Exponential Backoff: 5s, 10s, 20s...
        from datetime import timedelta
        delay_seconds = 5 * (2 ** (task.retry_count - 1))
        task.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
        
        return "READY", ExecutionPhase(task.execution_phase)

    def _normalize_payload(self, payload: any) -> any:
        """
        Ensures the payload adheres to basic contract types before Pydantic validation.
        Prevents common 'dict vs list' errors for artifacts.
        """
        if not isinstance(payload, dict):
            return payload

        # 1. Ensure artifacts is always a list
        artifacts = payload.get("artifacts")
        if artifacts is None or isinstance(artifacts, dict):
            payload["artifacts"] = []
        elif not isinstance(artifacts, list):
            payload["artifacts"] = []

        return payload

    async def process_response(self, session: AsyncSession, raw_payload: any, run_id: Optional[str] = None) -> Tuple[bool, str]:
        """
        The main intake pipeline. Executes strict validation steps in order.
        Returns (success, error_message).
        """
        # Safety Valve: Unwrap payload if it's still wrapped in an envelope
        if isinstance(raw_payload, dict) and "payload" in raw_payload and "event" not in raw_payload:
            logger.debug(f"[Guardian] Unwrapping payload from envelope for message {raw_payload.get('message_id')}")
            # Merge root envelope fields into the payload for WorkerResponse compatibility
            envelope = raw_payload
            business_data = raw_payload["payload"]
            if isinstance(business_data, dict):
                raw_payload = {
                    **business_data,
                    "message_id": envelope.get("message_id"),
                    "timestamp": envelope.get("timestamp"),
                    "protocol_version": envelope.get("protocol_version", "1.0"),
                    "event": envelope.get("event"),
                    "sender_role": envelope.get("sender_role"),
                    "state_revision": envelope.get("state_revision"),
                }

        # CENTRAL NORMALIZATION: Fix contract types before Pydantic validation
        raw_payload = self._normalize_payload(raw_payload)
        
        # FALLBACK: Extract run_id from payload if not explicitly provided
        if run_id is None and isinstance(raw_payload, dict):
            run_id = raw_payload.get("run_id")

        t0 = time.perf_counter_ns()
        try:
            if not raw_payload:
                return False, "Empty payload"

            if isinstance(raw_payload, str):
                try:
                    raw_payload = json.loads(raw_payload)
                except json.JSONDecodeError:
                    return False, "Invalid JSON transport"

            try:
                response = WorkerResponse(**raw_payload)
            except ValidationError as e:
                return False, f"Schema violation: {str(e)}"

            # 1. Task Existence Check (Slightly moved up to provide plan_id for idempotency)
            result = await session.execute(
                select(Task).options(joinedload(Task.plan).joinedload(Plan.project)).filter(Task.id == response.task_id)
            )
            task = result.scalars().first()
            if not task:
                return False, f"Task {response.task_id} not found"

            # 2. ATOMIC IDEMPOTENCY GATE
            # Now we have the 'task' object, so we can safely use task.plan_id.
            from engine.repository import MessageRepository
            msg_repo = MessageRepository()
            try:
                await msg_repo.mark_message_processed(
                    session=session,
                    run_id=run_id,
                    message_id=response.message_id,
                    plan_id=task.plan_id,
                    task_id=task.id,
                    sender=response.sender_role,
                    recipient="KERNEL",
                    msg_type="WORKER_RESPONSE"
                )
            except Exception as e:
                if "UNIQUE constraint failed" in str(e) or "Duplicate entry" in str(e):
                    logger.info(f"Message {response.message_id} already processed. Gate blocked duplicate.")
                    return True, "ALREADY_PROCESSED"
                raise e

            # 3. Terminal-State Check
            if task.execution_phase in [ExecutionPhase.COMPLETE, ExecutionPhase.FAILED, ExecutionPhase.FAILED_ITERATION_LIMIT]:
                return False, f"Task {task.id} is in terminal phase {task.execution_phase}. Rejected."

            # 4. Revision Check (Optimistic Concurrency)
            if response.state_revision != task.state_revision:
                telemetry.increment("cas_attempts")
                telemetry.increment("cas_conflicts")
                return False, f"Stale revision. Response: {response.state_revision}, Task: {task.state_revision}"

            # 5. SERIALIZATION LOCK (The Mutex)
            # Move from CLAIMED -> PROCESSING to block other event sources (like Timeouts)
            # This increments state_revision to X+1.
            # EXCEPTION: WORKER_TIMEOUT is a superseding recovery event and skips the locking phase.
            if task.state == "CLAIMED" and response.event != TaskEvent.WORKER_TIMEOUT.value:
                lock_success = await msg_repo.transition_task_atomic(
                    session=session,
                    project_id=task.plan.project_id,
                    task_id=task.id,
                    expected_revision=task.state_revision,
                    new_state="PROCESSING",
                    new_phase=task.execution_phase,
                    new_role=task.assigned_role,
                    triggering_message_id=f"lock-{response.message_id}",
                    run_id=run_id
                )
                if not lock_success:
                    return False, "Concurrency conflict: Task is already being processed by another event source."
                
                # Sync local object with DB to get the new state_revision (X+1) after the lock
                await session.refresh(task)
                logger.debug(f"[Guardian] Task {task.id} locked for processing (Rev {task.state_revision})")

            # 6. Role-Event Authorization
            if task.assigned_role is None:
                logger.error(f"[Invariant Violation] Task {task.id} has no assigned_role while in state {task.state}. This is an inconsistent state.")
                # Deterministic Fail-Fast: Mark the entire run as FAILED
                from engine.models import Run
                from sqlalchemy import update
                await session.execute(
                    update(Run)
                    .where(Run.id == run_id)
                    .values(
                        status="FAILED", 
                        failure_reason=f"Invariant Violation: Task {task.id} missing assigned_role in state {task.state}"
                    )
                )
                return False, f"Inconsistent State: Task {task.id} has no assigned_role"

            current_role = AssignedRole(task.assigned_role)
            current_phase = ExecutionPhase(task.execution_phase)
            response_role = AssignedRole(response.sender_role)
            
            if response_role != current_role and response_role != AssignedRole.SYSTEM:
                return False, f"Sender role {response.sender_role} does not match assigned role {current_role} and is not SYSTEM"

            if not GovernanceMatrix.authorize_event(current_phase, response_role, response.event):
                return False, f"Role {response.sender_role} is not authorized to trigger event {response.event} in phase {current_phase}"

            # 6. FSM Transition Validation
            try:
                transition_res = GovernanceMatrix.transition(current_phase, response.event)
            except IllegalTransitionError as e:
                return False, str(e)

            # Handle Artifact Contract for Code Submissions
            if response.event == TaskEvent.CODE_SUBMITTED:
                passed, error_code = self._validate_artifact_contract(response)
                if not passed:
                    logger.warning(f"[Guardian] Artifact Contract Violation for {task.id}: {error_code}")
                    
                    response_ts = self._normalize_utc(response.timestamp)
                    task_ts = self._normalize_utc(task.updated_at)
                    duration_ms = int((response_ts - task_ts).total_seconds() * 1000) if response_ts and task_ts else None
                    
                    await self._log_attempt(session, response, task, SubmissionOutcome.SCHEMA_ERROR, error_code=error_code, duration_ms=duration_ms, run_id=run_id)

                    task.attempt_count += 1
                    atomic_success = await msg_repo.transition_task_atomic(
                        session=session,
                        project_id=task.plan.project_id,
                        task_id=task.id,
                        expected_revision=task.state_revision,
                        new_state="READY",
                        new_phase=ExecutionPhase.CODING.value,
                        new_role=AssignedRole.CODER.value,
                        triggering_message_id=response.message_id,
                        run_id=run_id
                    )
                    
                    if atomic_success:
                        transition_log = TaskTransitionLog(
                            task_id=task.id,
                            from_phase=current_phase,
                            event=TaskEvent.SUBMISSION_INVALID_SCHEMA.value,
                            to_phase=ExecutionPhase.CODING.value,
                            sender_role=response.sender_role,
                            previous_revision=task.state_revision,
                            new_revision=task.state_revision + 1,
                            message_id=response.message_id,
                            timestamp=response.timestamp
                        )
                        session.add(transition_log)
                        return True, f"SCHEMA_INVALID_TRANSITIONED: {error_code}"
                    else:
                        return False, "Concurrency conflict during schema failure transition"

            if transition_res.next_phase == ExecutionPhase.CODING:
                if response.event in [TaskEvent.VERIFY_FAILURE, TaskEvent.REVIEW_FAILURE]:
                    task.attempt_count += 1
                    if task.attempt_count >= self.MAX_ITERATIONS:
                        transition_res = TransitionResult(
                            next_phase=ExecutionPhase.FAILED_ITERATION_LIMIT,
                            next_role=None
                        )

            # 7. Atomic Commit
            previous_phase = task.execution_phase
            response_ts = self._normalize_utc(response.timestamp)
            task_ts = self._normalize_utc(task.updated_at)
            duration_ms = int((response_ts - task_ts).total_seconds() * 1000) if response_ts and task_ts else None

            outcome = SubmissionOutcome.SUCCESS
            error_code = None
            if response.event in [TaskEvent.VERIFY_FAILURE, TaskEvent.REVIEW_FAILURE]:
                outcome = SubmissionOutcome.LOGIC_ERROR
                error_code = response.event.value

            await self._log_attempt(session, response, task, outcome, error_code=error_code, duration_ms=duration_ms, run_id=run_id)
            
            if response.artifacts:
                project_id = task.plan.project_id
                version = task.plan.version
                
                success = await self.artifact_store.persist_artifacts(
                    session,
                    project_id,
                    version,
                    task.id,
                    response.artifacts,
                    run_id=run_id
                )
                if not success:
                    telemetry.observe("transition_latency_ns", time.perf_counter_ns() - t0)
                    return False, "Artifact persistence failed"

            # Determine the next state
            if response.event == TaskEvent.PLAN_SUBMITTED.value:
                # SPECIAL CASE: Plan Submission
                # When a plan is submitted and accepted, the Planner task is COMPLETED, 
                # and we must instantiate the tasks defined in the plan.
                plan_data = response.plan_draft.model_dump() if response.plan_draft else {}
                
                # 1. Create the Plan object in DB
                new_plan = Plan(
                    id=str(uuid.uuid4()),
                    run_id=run_id,
                    project_id=task.plan.project_id,
                    version=task.plan.version + 1,
                    name=plan_data.get("plan_name", "Unnamed Plan"),
                    status="IN_PROGRESS"
                )
                session.add(new_plan)
                await session.flush()

                # 2. Create the Tasks defined in the plan
                for t_def in plan_data.get("tasks", []):
                    new_task = Task(
                        id=t_def.get("id", str(uuid.uuid4())),
                        run_id=run_id,
                        plan_id=new_plan.id,
                        description=t_def.get("description", ""),
                        state="READY",
                        execution_phase=ExecutionPhase.CODING.value,
                        assigned_role=t_def.get("role", AssignedRole.CODER.value),
                        expected_artifacts=t_def.get("expected_artifacts", []),
                        acceptance_criteria=t_def.get("acceptance_criteria", []),
                        state_revision=0,
                        updated_at=datetime.now(timezone.utc)
                    )
                    session.add(new_task)

                # 3. Update the Project to point to the new active plan
                await session.execute(
                    sql_update(Project)
                    .where(Project.id == task.plan.project_id)
                    .values(active_plan_id=new_plan.id)
                )

                # 4. Mark the Planner task as COMPLETE
                new_state = "VERIFIED" 
                next_phase_val = ExecutionPhase.CODING.value
                transition_res = TransitionResult(
                    next_phase=ExecutionPhase.CODING,
                    next_role=None
                )
            elif response.event == TaskEvent.WORKER_TIMEOUT.value:
                new_state, next_phase_val = await self._evaluate_retry_policy(session, task, response.event)
                # Update the transition result for the atomic commit
                # IMPORTANT: Maintain the current assigned_role during recovery to prevent "Role Amnesia"
                transition_res = TransitionResult(
                    next_phase=next_phase_val, 
                    next_role=AssignedRole(task.assigned_role) if task.assigned_role else None
                )
            elif transition_res.next_phase == ExecutionPhase.COMPLETE:
                new_state = "VERIFIED"
            elif transition_res.next_phase == ExecutionPhase.FAILED_ITERATION_LIMIT:
                new_state = "FAILED"
            elif transition_res.next_phase == ExecutionPhase.FAILED:
                new_state = "FAILED"
            elif transition_res.next_role == AssignedRole.SYSTEM:
                new_state = "SUBMITTED"
            else:
                # Any transition to a Worker role must be READY for the scheduler to pick it up
                new_state = "READY"

            # TRIGGER TERMINAL RUN FAILURE
            # If the task transitioned to FAILED (especially in PLANNING), the whole run is failed.
            if transition_res.next_phase in [ExecutionPhase.FAILED, ExecutionPhase.FAILED_ITERATION_LIMIT]:
                Narrator.failure(task.id, f"Event {response.event} led to terminal state", run_id, terminal=True)
                from engine.models import Run
                from sqlalchemy import update
                await session.execute(
                    update(Run)
                    .where(Run.id == run_id)
                    .values(
                        status="FAILED", 
                        failure_reason=f"Task {task.id} failed with event {response.event}. Logs: {(response.logs[:500] if response.logs else 'No logs available')}"
                    )
                )

            atomic_success = await msg_repo.transition_task_atomic(
                session=session,
                project_id=task.plan.project_id,
                task_id=task.id,
                expected_revision=task.state_revision,
                new_state=new_state,
                new_phase=transition_res.next_phase.value,
                new_role=transition_res.next_role.value if transition_res.next_role else None,
                triggering_message_id=response.message_id,
                run_id=run_id
            )
            
            if not atomic_success:
                telemetry.observe("transition_latency_ns", time.perf_counter_ns() - t0)
                return False, "Concurrency conflict: Task state changed by another worker."

            transition_log = TaskTransitionLog(
                task_id=task.id,
                from_phase=previous_phase,
                event=response.event.value,
                to_phase=transition_res.next_phase.value,
                sender_role=response.sender_role.value,
                previous_revision=task.state_revision,
                new_revision=task.state_revision + 1,
                message_id=response.message_id,
                timestamp=response.timestamp
            )
            session.add(transition_log)

            # Trigger narrative worker response log
            Narrator.worker_response(task.id, response.event.value, response.sender_role.value, run_id)
            
            if previous_phase != transition_res.next_phase.value:
                Narrator.phase_change(transition_res.next_phase.value)
            
            Narrator.transition(task.id, previous_phase, transition_res.next_phase.value, response.event.value)
            
            telemetry.observe("transition_latency_ns", time.perf_counter_ns() - t0)
            return True, "SUCCESS"

        except Exception as e:
            telemetry.observe("transition_latency_ns", time.perf_counter_ns() - t0)
            try:
                if 'response' in locals() and 'task' in locals():
                    await self._log_attempt(session, response, task, SubmissionOutcome.WORKER_ERROR, error_code=str(e), run_id=run_id)
            except Exception as log_e:
                logger.error(f"Failed to log worker error: {log_e}")

            logger.exception(f"Guardian Pipeline encountered an unexpected error: {str(e)}")
            return False, f"Internal Guardian Error: {str(e)}"
