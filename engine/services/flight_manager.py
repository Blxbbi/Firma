import logging
import uuid
import asyncio
from datetime import datetime, timezone

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from engine.models import (
    Project, Plan, Task, ExecutionPhase, TaskEvent, 
    AssignedRole, SubmissionOutcome, WorkerResponse
)
from engine.repository import MessageRepository
from engine.services.guardian import GuardianPipeline
from engine.services.artifact_store import ArtifactStore
from engine.services.observability import ObservabilityService
from engine.db import DatabaseManager

logger = logging.getLogger(__name__)

class FlightSpec(BaseModel):
    """
    Defines a specific flight test case.
    """
    flight_id: str = Field(default_factory=lambda: f"FLIGHT-{str(uuid.uuid4())[:8]}")
    flight_class: str # "A", "B", "C"
    goal: str
    constraints: List[str] = []
    expected_artifacts: List[Dict[str, str]] = [] # [{"path": "...", "type": "..."}]
    acceptance_criteria: List[str] = []
    model_name: str = "gpt-4o" # Default model for the flight

class FlightResult(BaseModel):
    flight_id: str
    project_id: str
    task_id: str
    final_state: str
    total_iterations: int
    duration_seconds: float
    success: bool
    error_log: Optional[str] = None

class FlightManager:
    """
    FlightManager: Orchestrates the 'Flight Program' for real-world testing.
    Fully Asynchronous implementation.
    """

    def __init__(self, db_manager: DatabaseManager, artifact_root: str = "artifact_store/flights"):
        self.db_manager = db_manager
        self.artifact_root = artifact_root
        self.artifact_store = ArtifactStore(base_dir=artifact_root)
        self.guardian = GuardianPipeline(self.artifact_store)
        self.repo = MessageRepository(artifact_store_root=artifact_root)

    async def execute_flight(self, spec: FlightSpec, worker_provider: Any, run_id: Optional[str] = None) -> FlightResult:
        """
        Executes a single flight spec asynchronously.
        Drives the FSM until a terminal state is reached.
        """
        start_time = datetime.now(timezone.utc)
        
        async with self.db_manager.session_scope() as session:
            try:
                # 1. Initialize Project & Task
                project = Project(id=f"PROJ-{spec.flight_id}", name=f"Flight {spec.flight_id}", run_id=run_id)
                session.add(project)
                await session.flush()
                
                plan = Plan(id=f"PLAN-{spec.flight_id}", project_id=project.id, run_id=run_id, version=1, name="Flight Plan", status="IN_PROGRESS")
                session.add(plan)
                await session.flush()
                
                project.active_plan_id = plan.id
                
                task = Task(
                    id=f"TASK-{spec.flight_id}",
                    run_id=run_id,
                    plan_id=plan.id,
                    description=spec.goal,
                    state="CODING",
                    execution_phase=ExecutionPhase.CODING.value,
                    assigned_role=AssignedRole.CODER.value,
                    state_revision=1,
                    expected_artifacts=[{"path": a["path"], "type": a["type"]} for a in spec.expected_artifacts],
                    acceptance_criteria=spec.acceptance_criteria
                )
                session.add(task)
                await session.flush()
                
                # 2. Execution Loop
                iteration = 0
                while True:
                    # Refresh task state from DB
                    await session.refresh(task)
                    
                    if task.execution_phase in [ExecutionPhase.COMPLETE.value, ExecutionPhase.FAILED.value, ExecutionPhase.FAILED_ITERATION_LIMIT.value]:
                        break
                    
                    current_phase = ExecutionPhase(task.execution_phase)
                    
                    if current_phase == ExecutionPhase.CODING:
                        prompt = f"Goal: {spec.goal}\nConstraints: {spec.constraints}\nExpected Artifacts: {spec.expected_artifacts}"
                        response_payload = await worker_provider.generate_response(
                            task_id=task.id,
                            state_revision=task.state_revision,
                            prompt=prompt,
                            model_name=spec.model_name
                        )
                        
                        success, result = await self.guardian.process_response(session, response_payload, run_id=run_id)
                        if not success:
                            logger.error(f"Flight {spec.flight_id}: Guardian rejected submission: {result}")
                        
                        # Note: session_scope handles commit
                        iteration += 1

                    elif current_phase == ExecutionPhase.VERIFYING:
                        verification_payload = {
                            "message_id": str(uuid.uuid4()),
                            "task_id": task.id,
                            "state_revision": task.state_revision,
                            "sender_role": "SYSTEM",
                            "event": "VERIFY_SUCCESS", 
                            "timestamp": datetime.now(timezone.utc)
                        }
                        success, result = await self.guardian.process_response(session, verification_payload, run_id=run_id)

                    elif current_phase == ExecutionPhase.REVIEWING:
                        review_payload = {
                            "message_id": str(uuid.uuid4()),
                            "task_id": task.id,
                            "state_revision": task.state_revision,
                            "sender_role": "REVIEWER",
                            "event": "REVIEW_APPROVED",
                            "timestamp": datetime.now(timezone.utc)
                        }
                        success, result = await self.guardian.process_response(session, review_payload, run_id=run_id)
                    
                    else:
                        logger.error(f"Flight {spec.flight_id}: Unexpected phase {current_phase}")
                        break
                
                end_time = datetime.now(timezone.utc)
                duration = (end_time - start_time).total_seconds()
                
                return FlightResult(
                    flight_id=spec.flight_id,
                    project_id=project.id,
                    task_id=task.id,
                    final_state=task.execution_phase,
                    total_iterations=iteration,
                    duration_seconds=duration,
                    success=(task.execution_phase == ExecutionPhase.COMPLETE.value)
                )
                        
            except Exception as e:
                logger.exception(f"Flight {spec.flight_id} crashed: {str(e)}")
                # session_scope handles rollback
                return FlightResult(
                    flight_id=spec.flight_id,
                    project_id=f"PROJ-{spec.flight_id}",
                    task_id=f"TASK-{spec.flight_id}",
                    final_state="CRASHED",
                    total_iterations=iteration if 'iteration' in locals() else 0,
                    duration_seconds=0,
                    success=False,
                    error_log=str(e)
                )

    async def run_batch(self, specs: List[FlightSpec], worker_provider: Any, run_id: Optional[str] = None) -> List[FlightResult]:
        """Runs a batch of flights asynchronously in parallel."""
        logger.info(f"🚀 Launching batch of {len(specs)} flights...")
        tasks = [self.execute_flight(spec, worker_provider, run_id=run_id) for spec in specs]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        final_results = []
        for i, res in enumerate(results):
            spec = specs[i]
            if isinstance(res, Exception):
                logger.error(f"🏁 Flight {spec.flight_id} failed with exception: {res}")
                final_results.append(FlightResult(
                    flight_id=spec.flight_id,
                    project_id=f"PROJ-{spec.flight_id}",
                    task_id=f"TASK-{spec.flight_id}",
                    final_state="CRASHED",
                    total_iterations=0,
                    duration_seconds=0,
                    success=False,
                    error_log=str(res)
                ))
            else:
                logger.info(f"🏁 Flight {spec.flight_id} completed: {res.final_state} | Success: {res.success}")
                final_results.append(res)
                
        return final_results
