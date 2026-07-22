import json
import logging
from typing import List, Optional, Dict, Any, Set
from pydantic import BaseModel, Field, ValidationError, field_validator

logger = logging.getLogger(__name__)

class AcceptanceCriterion(BaseModel):
    type: str # e.g., "command", "exists"
    value: str # the actual command or path

class TaskSpec(BaseModel):
    id: str
    description: str
    role: str
    dependencies: List[str] = Field(default_factory=list)
    acceptance_criteria: List[AcceptanceCriterion]

class PlanSpec(BaseModel):
    version: str
    project_id: str
    tasks: List[TaskSpec]

class ValidationResult:
    def __init__(self, approved: bool, errors: List[str], parsed_plan: Optional[PlanSpec] = None):
        self.approved = approved
        self.errors = errors
        self.parsed_plan = parsed_plan

    def __repr__(self):
        return f"ValidationResult(approved={self.approved}, errors={self.errors})"

class SpecGate:
    """
    SpecGate: The deterministic filter for Plan execution.
    
    Ensures that a plan is not only structurally correct (JSON/Schema) 
    but also semantically executable (No cycles, valid roles, etc.).
    """

    ALLOWED_ROLES = {"PLANNER", "CODER", "REVIEWER", "RESEARCHER"}

    @classmethod
    def validate(cls, plan_str: str) -> ValidationResult:
        # 1. Structural Validation (Ebene A)
        try:
            data = json.loads(plan_str)
            plan = PlanSpec(**data)
        except json.JSONDecodeError as e:
            return ValidationResult(False, [f"Invalid JSON: {str(e)}"])
        except ValidationError as e:
            errors = [f"{err['loc']}: {err['msg']}" for err in e.errors()]
            return ValidationResult(False, errors)

        # 2. Semantic Validation (Ebene B)
        semantic_errors = []
        
        # Check: Unique Task IDs
        task_ids = [t.id for t in plan.tasks]
        if len(task_ids) != len(set(task_ids)):
            semantic_errors.append("Duplicate task IDs found in plan.")

        # Check: Valid Roles
        for task in plan.tasks:
            if task.role not in cls.ALLOWED_ROLES:
                semantic_errors.append(f"Task {task.id} has invalid role: {task.role}. Allowed: {cls.ALLOWED_ROLES}")
            
            # Check: Minimum 1 criterion
            if not task.acceptance_criteria:
                semantic_errors.append(f"Task {task.id} must have at least one acceptance criterion.")

        # Check: Dependency Existence
        all_ids = set(task_ids)
        for task in plan.tasks:
            for dep in task.dependencies:
                if dep not in all_ids:
                    semantic_errors.append(f"Task {task.id} depends on non-existent task {dep}.")

        # Check: Cyclic Dependencies
        if cls._has_cycle(plan.tasks):
            semantic_errors.append("Cyclic dependencies detected in the task graph.")

        if semantic_errors:
            return ValidationResult(False, semantic_errors)

        return ValidationResult(True, [], plan)

    @classmethod
    def _has_cycle(cls, tasks: List[TaskSpec]) -> bool:
        adj = {t.id: t.dependencies for t in tasks}
        visited = set()
        rec_stack = set()

        def visit(u):
            visited.add(u)
            rec_stack.add(u)
            for v in adj.get(u, []):
                if v not in visited:
                    if visit(v): return True
                elif v in rec_stack:
                    return True
            rec_stack.remove(u)
            return False

        for task in tasks:
            if task.id not in visited:
                if visit(task.id): return True
        return False
