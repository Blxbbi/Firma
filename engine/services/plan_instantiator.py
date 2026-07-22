from sqlalchemy.orm import Session
from typing import Dict, List
from engine.models import Plan, Task, PlanDraftSchema
import logging

logger = logging.getLogger(__name__)

class PlanInstantiationError(Exception):
    """Custom exception for plan instantiation failures."""
    def __init__(self, message: str, error_code: str):
        super().__init__(message)
        self.error_code = error_code

class PlanInstantiationService:
    """
    Service responsible for transforming a PlanDraftSchema into persistent 
    Plan and Task records in the database.
    """

    def __init__(self, db_session: Session):
        self.db = db_session

    def instantiate_plan(self, draft: PlanDraftSchema) -> Plan:
        """
        Atomically creates a Plan and its associated Tasks.
        
        Steps:
        1. Validate task integrity (IDs, duplicates).
        2. Check for circular dependencies.
        3. Determine initial states (READY or BLOCKED).
        4. Persist to DB within a single transaction.
        """
        try:
            # 1. Integrity & Duplicate Check
            task_map = self._validate_and_map_tasks(draft.tasks)
            
            # 2. Circular Dependency Check
            self._check_circular_dependencies(task_map)

            # 3. Start Transaction
            # Note: In SQLAlchemy, the session is already a transaction. 
            # We use the session to add objects and commit at the end.
            
            new_plan = Plan(
                name=draft.plan_name,
                status='PLANNED',
                version=1
            )
            self.db.add(new_plan)
            self.db.flush()  # Get new_plan.id

            for task_draft in draft.tasks:
                # Determine initial state
                # If no dependencies, it's READY. Otherwise, it's BLOCKED.
                initial_state = "READY" if not task_draft.dependencies else "BLOCKED"

                new_task = Task(
                    id=task_draft.id,
                    plan_id=new_plan.id,
                    description=task_draft.description,
                    state=initial_state,
                    execution_phase="CODING",
                    assigned_role="CODER",
                    state_revision=0,
                    dependencies=task_draft.dependencies,
                    expected_artifacts=[a.model_dump() for a in task_draft.expected_artifacts],
                    acceptance_criteria=task_draft.acceptance_criteria
                )
                self.db.add(new_task)

            self.db.commit()
            logger.info(f"Successfully instantiated plan: {new_plan.id} ({draft.plan_name}) with {len(draft.tasks)} tasks.")
            return new_plan

        except PlanInstantiationError as e:
            self.db.rollback()
            logger.error(f"Plan instantiation failed: {e.error_code} - {str(e)}")
            raise
        except Exception as e:
            self.db.rollback()
            logger.error(f"Unexpected error during plan instantiation: {str(e)}")
            raise PlanInstantiationError(str(e), "ERR_INTERNAL_ERROR")

    def _validate_and_map_tasks(self, tasks: List) -> Dict[str, any]:
        """Validates task integrity and returns a map for easy access."""
        task_map = {}
        seen_ids = set()

        for t in tasks:
            if not t.id:
                raise PlanInstantiationError("Task ID cannot be empty", "ERR_INVALID_TASK_ID")
            if t.id in seen_ids:
                raise PlanInstantiationError(f"Duplicate Task ID: {t.id}", "ERR_DUPLICATE_TASK_ID")
            
            seen_ids.add(t.id)
            task_map[t.id] = t

        # Check if all dependencies exist in the task list
        for t in tasks:
            for dep_id in t.dependencies:
                if dep_id not in task_map:
                    raise PlanInstantiationError(f"Task {t.id} depends on non-existent task {dep_id}", "ERR_MISSING_DEPENDENCY")

        return task_map

    def _check_circular_dependencies(self, task_map: Dict[str, any]):
        """Uses DFS to detect cycles in the dependency graph."""
        visited = set()
        path = set()

        def visit(task_id: str):
            if task_id in path:
                return True
            if task_id in visited:
                return False
            
            visited.add(task_id)
            path.add(task_id)
            
            # dependencies are the things this task depends ON
            for dep_id in task_map[task_id].dependencies:
                if visit(dep_id):
                    return True
            
            path.remove(task_id)
            return False

        for task_id in task_map:
            if task_id not in visited:
                if visit(task_id):
                    raise PlanInstantiationError("Circular dependency detected in plan", "ERR_CIRCULAR_DEPENDENCY")

