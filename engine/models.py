from enum import Enum
from sqlalchemy import Column, String, Integer, Boolean, ForeignKey, DateTime, Text, JSON, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

import uuid
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Dict, Any, Optional, List

Base = declarative_base()

# --- Enums ---

class MessageType(str, Enum):
    WORKER_RESPONSE = "WORKER_RESPONSE"
    SYSTEM_COMMAND = "SYSTEM_COMMAND"
    VALIDATION_RESULT = "VALIDATION_RESULT"

class RunStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

class ExecutionPhase(str, Enum):
    PLANNING = "PLANNING"
    RESEARCHING = "RESEARCHING"
    CODING = "CODING"
    VERIFYING = "VERIFYING"
    REVIEWING = "REVIEWING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    FAILED_ITERATION_LIMIT = "FAILED_ITERATION_LIMIT"

class AssignedRole(str, Enum):
    PLANNER = "PLANNER"
    RESEARCHER = "RESEARCHER"
    CODER = "CODER"
    VERIFIER = "VERIFIER"
    REVIEWER = "REVIEWER"
    SYSTEM = "SYSTEM"

class TaskEvent(str, Enum):
    PLAN_SUBMITTED = "PLAN_SUBMITTED"
    PLAN_APPROVED = "PLAN_APPROVED"
    PLAN_REJECTED = "PLAN_REJECTED"
    RESEARCH_COMPLETE = "RESEARCH_COMPLETE"
    CODE_SUBMITTED = "CODE_SUBMITTED"
    SUBMISSION_INVALID_SCHEMA = "SUBMISSION_INVALID_SCHEMA"
    VERIFY_SUCCESS = "VERIFY_SUCCESS"
    VERIFY_FAILURE = "VERIFY_FAILURE"
    REVIEW_APPROVED = "REVIEW_APPROVED"
    REVIEW_FAILURE = "REVIEW_FAILURE"
    TASK_FAILED = "TASK_FAILED"
    ITERATION_LIMIT_REACHED = "ITERATION_LIMIT_REACHED"
    WORKER_TIMEOUT = "WORKER_TIMEOUT"

class RunStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

class SubmissionOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    SCHEMA_ERROR = "SCHEMA_ERROR"
    LOGIC_ERROR = "LOGIC_ERROR"
    WORKER_ERROR = "WORKER_ERROR"
    TIMEOUT = "TIMEOUT"

class FileAction(str, Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"

# --- Pydantic Models (for Messages / API / Schemas) ---

class MessageHeader(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: Optional[str] = None
    plan_id: Optional[str] = None
    sender: str
    recipient: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    message_type: MessageType

    version: str = "1.0"
    schema_version: str = "1.1"

class Message(BaseModel):
    header: MessageHeader
    payload: Dict[str, Any]

class GuardResult(BaseModel):
    passed: bool
    error_code: Optional[str] = None
    reason: Optional[str] = None

# --- LLM Response Schemas ---

class ArtifactChange(BaseModel):
    path: str
    content: Optional[str] = None
    action: FileAction

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        if v.startswith("/") or v.startswith("\\") or ".." in v:
            raise ValueError("Invalid path: Absolute paths and path traversal are not allowed.")
        return v

    @model_validator(mode="after")
    def validate_content_rules(self) -> "ArtifactChange":
        if self.action in {FileAction.CREATE, FileAction.UPDATE}:
            if self.content is None:
                raise ValueError(f"Content is required for action '{self.action.value}'")
        if self.action == FileAction.DELETE:
            if self.content is not None:
                raise ValueError("DELETE action must not contain content")
        return self

class LLMResponse(BaseModel):
    artifacts: List[ArtifactChange]
    logs: Optional[str] = None
    thinking: Optional[str] = None

class WorkerResponse(BaseModel):
    protocol_version: str = "1.0"
    message_id: str
    task_id: str
    run_id: Optional[str] = None  # Correlation scope. task_id is unique ONLY within run_id (see MessageLog filter on (task_id, run_id)).
    state_revision: int
    event: TaskEvent
    sender_role: AssignedRole # Added for explicit role authorization
    artifacts: Optional[List[Any]] = None
    timestamp: datetime # Removed default_factory to force explicit timestamp from provider
    logs: Optional[str] = None
    plan_draft: Optional["PlanDraftSchema"] = None


# --- Planner Schemas ---

class PlannedArtifact(BaseModel):
    path: str
    type: FileAction

class TaskDefinition(BaseModel):
    id: str
    description: str
    dependencies: List[str] = Field(default_factory=list)
    expected_artifacts: List[PlannedArtifact]
    acceptance_criteria: List[str]
    # Phase 2 (Idee A): edit-contract (H1/H2)
    scope_files: List[str] = Field(default_factory=list)        # relative paths the CODER may CREATE/UPDATE
    protected_files: List[str] = Field(default_factory=list)    # relative paths the CODER must NOT touch (any action)
    edit_mode: str = "auto"                                   # "auto" | "force_edit" | "force_create"
    allow_delete: bool = False                                 # V1: deletes allowed only if explicitly True

    @field_validator("scope_files", "protected_files")
    @classmethod
    def _validate_rel_paths(cls, v):
        out = []
        seen = set()
        for p in v:
            if p.startswith("/") or p.startswith("\\") or ".." in p:
                raise ValueError(f"Invalid path (absolute or traversal): {p!r}")
            norm = p.replace("\\", "/")
            if norm in seen:
                continue  # dedupe, stable order
            seen.add(norm)
            out.append(norm)
        return out

    @field_validator("edit_mode")
    @classmethod
    def _validate_edit_mode(cls, v):
        if v not in ("auto", "force_edit", "force_create"):
            raise ValueError(f"edit_mode must be one of auto|force_edit|force_create, got {v!r}")
        return v

class PlannerOutput(BaseModel):
    plan_name: str
    tasks: List[TaskDefinition]

# --- Task/Plan Schemas ---

class TaskDraftSchema(BaseModel):
    id: str
    description: str
    dependencies: List[str] = Field(default_factory=list)
    expected_artifacts: List[PlannedArtifact]
    acceptance_criteria: List[str]
    # Phase 2 (Idee A): edit-contract (carried through the planner draft; the kernel
    # fills protected_files deterministically in ingest mode, see scope_policy.py)
    scope_files: List[str] = Field(default_factory=list)
    protected_files: List[str] = Field(default_factory=list)
    edit_mode: str = "auto"
    allow_delete: bool = False

    @field_validator("scope_files", "protected_files")
    @classmethod
    def _validate_rel_paths(cls, v):
        out = []
        seen = set()
        for p in v:
            if p.startswith("/") or p.startswith("\\") or ".." in p:
                raise ValueError(f"Invalid path (absolute or traversal): {p!r}")
            norm = p.replace("\\", "/")
            if norm in seen:
                continue
            seen.add(norm)
            out.append(norm)
        return out

    @field_validator("edit_mode")
    @classmethod
    def _validate_edit_mode(cls, v):
        if v not in ("auto", "force_edit", "force_create"):
            raise ValueError(f"edit_mode must be one of auto|force_edit|force_create, got {v!r}")
        return v

class PlanDraftSchema(BaseModel):
    plan_name: str
    tasks: List[TaskDraftSchema]

# --- SQLAlchemy Models (for Database) ---

class Run(Base):
    """
    An isolated execution instance. 
    All entities in a run share the same run_id to prevent cross-talk.
    """
    __tablename__ = 'runs'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    status = Column(String, nullable=False, default="ACTIVE") # 'ACTIVE', 'COMPLETED', 'FAILED', 'CANCELLED'
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    config_json = Column(JSON, nullable=True) # Stores the configuration used for this run
    metrics_json = Column(JSON, nullable=True) # Stores aggregate metrics (write-only for Runtime)
    failure_reason = Column(String, nullable=True)
    is_milestone = Column(Boolean, default=False)


class Project(Base):
    """
    The top-level entity. A project is a long-lived objective.
    """
    __tablename__ = 'projects'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id = Column(String, ForeignKey('runs.id'), index=True, nullable=False)
    name = Column(String, nullable=False)
    status = Column(String, nullable=False, default="ACTIVE") # 'ACTIVE', 'ARCHIVED', 'FAILED'
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    current_plan_id = Column(String, ForeignKey('plans.id'), nullable=True)
    active_plan_id = Column(String, ForeignKey('plans.id'), nullable=True)

    plans = relationship("Plan", back_populates="project", foreign_keys="[Plan.project_id]", lazy="raise")

class Plan(Base):
    """
    A specific, immutable snapshot of a project's execution strategy.
    """
    __tablename__ = 'plans'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id = Column(String, ForeignKey('runs.id'), index=True, nullable=False)
    project_id = Column(String, ForeignKey('projects.id'), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    name = Column(String, nullable=False)
    status = Column(String, nullable=False, default="PLANNED") # 'PLANNED', 'IN_PROGRESS', 'COMPLETED', 'FAILED', 'SUPERSEDED'
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    immutable = Column(Boolean, default=True)

    project = relationship("Project", back_populates="plans", foreign_keys=[project_id], lazy="raise")
    tasks = relationship("Task", back_populates="plan", cascade="all, delete-orphan", lazy="raise")

class Task(Base):
    """
    A concrete unit of work within a specific Plan version.
    """
    __tablename__ = 'tasks'
    id = Column(String, primary_key=True)
    run_id = Column(String, ForeignKey('runs.id'), index=True, nullable=False)
    plan_id = Column(String, ForeignKey('plans.id'), nullable=False)
    description = Column(String, nullable=True)
    state = Column(String, nullable=False) 
    
    execution_phase = Column(String, nullable=False, default="PLANNING") 
    assigned_role = Column(String, nullable=True, default="PLANNER")    
    state_revision = Column(Integer, nullable=False, default=0)         
    attempt_count = Column(Integer, nullable=False, default=0)          
    
    # Lease Semantics for Industrial Recovery
    claimed_at = Column(DateTime(timezone=True), nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    
    verification_type = Column(String, nullable=True) # EXPLICIT GOVERNANCE: How this task is verified
    assigned_worker = Column(String, nullable=True)
    assignment_timeout = Column(DateTime(timezone=True), nullable=True)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)
    dependencies = Column(JSON, default=[]) 
    expected_artifacts = Column(JSON, nullable=False)
    acceptance_criteria = Column(JSON, nullable=False)
    last_review_feedback = Column(Text, nullable=True)  # Phase 6.1: REVIEW_FAILURE-Feedback fuer CODER-Retries
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    plan = relationship("Plan", back_populates="tasks", lazy="raise")
    artifacts = relationship("Artifact", back_populates="task", cascade="all, delete-orphan", lazy="raise")
    events = relationship("TaskEventLog", back_populates="task", cascade="all, delete-orphan", lazy="raise")

class Artifact(Base):
    """
    A physical file produced by a task.
    """
    __tablename__ = 'artifacts'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(String, ForeignKey('tasks.id'), nullable=False)
    path = Column(String, nullable=False)
    hash = Column(String, nullable=False)
    storage_path = Column(String, nullable=False)
    version = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    task = relationship("Task", back_populates="artifacts", lazy="raise")

class MessageLog(Base):
    """
    Immutable log of all messages processed by the engine.
    """
    __tablename__ = 'message_log'
    message_id = Column(String, primary_key=True)
    run_id = Column(String, ForeignKey('runs.id'), index=True, nullable=False)
    plan_id = Column(String, nullable=False)
    task_id = Column(String, nullable=True)
    sender = Column(String, nullable=False)
    recipient = Column(String, nullable=False)
    message_type = Column(String, nullable=False)
    type_version = Column(String, nullable=False)
    received_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    processing_status = Column(String, nullable=False)
    error_reason = Column(Text, nullable=True)

class TaskEventLog(Base):
    """
    Audit trail of state transitions for tasks.
    """
    __tablename__ = 'task_events'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(String, ForeignKey('tasks.id'), nullable=False)
    previous_state = Column(String)
    new_state = Column(String)
    triggering_message_id = Column(String)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    task = relationship("Task", back_populates="events", lazy="raise")

class ProcessedEvent(Base):
    """
    Idempotency layer: tracks processed worker messages.
    """
    __tablename__ = 'processed_events'
    message_id = Column(String, primary_key=True)
    task_id = Column(String, ForeignKey('tasks.id'), nullable=False)
    revision = Column(Integer, nullable=False)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class TaskTransitionLog(Base):
    """
    Event Sourcing: Detailed log of every phase transition.
    """
    __tablename__ = 'task_transition_log'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(String, ForeignKey('tasks.id'), nullable=False)
    from_phase = Column(String, nullable=False)
    event = Column(String, nullable=False)
    to_phase = Column(String, nullable=False)
    sender_role = Column(String, nullable=False)
    previous_revision = Column(Integer, nullable=False)
    new_revision = Column(Integer, nullable=False)
    message_id = Column(String, nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)

class SubmissionLog(Base):
    """
    Attempt Log: Records every single worker attempt to resolve a task.
    """
    __tablename__ = 'submission_log'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id = Column(String, index=True, nullable=True)
    task_id = Column(String, ForeignKey('tasks.id'), nullable=False)
    project_id = Column(String, nullable=False)
    revision = Column(Integer, nullable=False)
    message_id = Column(String, nullable=False)
    worker_id = Column(String, nullable=True)
    model_name = Column(String, nullable=True)
    model_version = Column(String, nullable=True)
    worker_build_version = Column(String, nullable=True)
    prompt_hash = Column(String, nullable=True)
    artifact_contract_version = Column(String, nullable=False, default="1.0")
    outcome = Column(String, nullable=False)
    error_code = Column(String, nullable=True)
    iteration_number = Column(Integer, nullable=False)
    duration_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class SystemMetric(Base):
    """
    Telemetry for system-level performance metrics.
    """
    __tablename__ = 'system_metrics'
    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String, index=True, nullable=True)
    metric_name = Column(String, nullable=False, index=True)
    value = Column(Float, nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    metadata_json = Column(JSON, nullable=True)

class PlanRevision(Base):
    __tablename__ = 'plan_revisions'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    plan_id = Column(String, ForeignKey('plans.id'), nullable=False)
    requested_by = Column(String, nullable=False)
    revision_payload = Column(JSON, nullable=False)
    status = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    resolved_at = Column(DateTime(timezone=True), nullable=True)
