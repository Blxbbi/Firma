import os
import asyncio
import logging
import uuid
import tempfile
import json
import re
from pathlib import Path
from sqlalchemy.orm import Session
from typing import Dict, Any

from engine.models import Base, Project, Plan, Task, Message, MessageHeader, MessageType
from engine.db import DatabaseManager
from engine.repository import MessageRepository
from engine.workflow import process_task_message
from engine.services.sandbox import LocalSandbox
from engine.services.execution import ExecutionService
from engine.orchestrator import Orchestrator

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("stability-runner")

class StabilityMockProvider:
    """
    A deterministic provider that returns predefined responses 
    to test Engine stability without external dependencies.
    """
    def __init__(self, scenario: str):
        self.scenario = scenario

    def generate(self, system_prompt: str, user_prompt: str, timeout: int = 60) -> str:
        match = re.search(r"Task (T\d+)", user_prompt)
        task_id = match.group(1) if match else "T1"
        
        if task_id == "T1":
            return json.dumps({
                "artifacts": [
                    {"path": "game.py", "content": "def play(): print('Game running')\\n", "action": "CREATE"}
                ]
            })
        elif task_id == "T2":
            if self.scenario == "FAILURE":
                return json.dumps({
                    "artifacts": [
                        {"path": "cli.py", "content": "import non_existent_module\\n", "action": "CREATE"}
                    ]
                })
            return json.dumps({
                "artifacts": [
                    {"path": "cli.py", "content": "import game\\nprint('CLI ready')", "action": "CREATE"}
                ]
            })
        return json.dumps({"artifacts": []})

    def generate_json(self, system_prompt: str, user_prompt: str, schema: Dict[str, Any], timeout: int = 60) -> Dict[str, Any]:
        return {
            "plan_name": "Stability Mock Plan",
            "tasks": [
                {
                    "id": "T1", 
                    "description": "Implement core game logic in game.py", 
                    "dependencies": [], 
                    "expected_artifacts": [{"path": "game.py", "type": "CREATE"}], 
                    "acceptance_criteria": ["EXISTS:game.py", "CMD:python -c \"import game\""]
                },
                {
                    "id": "T2", 
                    "description": "Implement CLI interface in cli.py", 
                    "dependencies": ["T1"], 
                    "expected_artifacts": [{"path": "cli.py", "type": "CREATE"}], 
                    "acceptance_criteria": ["EXISTS:cli.py", "CMD:python -c \"import cli\""]
                }
            ]
        }

async def run_stability_test(prompt: str, scenario: str = "SUCCESS"):
    """
    Stability Run: Verifies that the Engine is resilient and crash-free.
    """
    logger.info(f"🧪 Starting Stability Run: {prompt} (Scenario: {scenario})")
    
    db_file = f"stability_{scenario.lower()}.db"
    if os.path.exists(db_file): os.remove(db_file)
    db_manager = DatabaseManager(db_url=f"sqlite:///{db_file}")
    db_manager.create_tables(Base)
    
    artifact_dir = tempfile.TemporaryDirectory()
    os.environ["FIRMA_ARTIFACT_STORE_DIR"] = artifact_dir.name
    
    sandbox = LocalSandbox(base_workdir=f"stability_{scenario.lower()}_sandbox")
    repo = MessageRepository(artifact_store_root=artifact_dir.name)
    exec_service = ExecutionService(sandbox)
    
    class SimpleScheduler:
        def assign_unassigned_ready_tasks(self, session):
            from engine.models import Task
            ready_tasks = session.query(Task).filter(Task.state == "READY").all()
            for task in ready_tasks:
                task.state = "CLAIMED"
                logger.info(f"Scheduler claimed task {task.id}")
    
    scheduler = SimpleScheduler()
    orchestrator = Orchestrator(db_manager, scheduler, exec_service, sandbox)
    provider = StabilityMockProvider(scenario)
    
    project_id = f"proj_{uuid.uuid4().hex[:8]}"
    with db_manager.session_scope() as session:
        proj = Project(id=project_id, name="Stability Test")
        session.add(proj)
    
    logger.info("--- Phase 1: Planning ---")
    plan_data = provider.generate_json("", prompt, {})

    with db_manager.session_scope() as session:
        plan = Plan(
            id=str(uuid.uuid4()), 
            project_id=project_id, 
            name=plan_data.get("plan_name", "Stability Plan"), 
            status="IN_PROGRESS", 
            version=1
        )
        session.add(plan)
        project = session.query(Project).filter_by(id=project_id).first()
        project.active_plan_id = plan.id
        
        for i, t_def in enumerate(plan_data.get("tasks", [])):
            task_id = f"T{i+1}"
            initial_state = "READY" if not t_def.get("dependencies") else "BLOCKED"
            task = Task(
                id=task_id, 
                plan_id=plan.id, 
                description=t_def["description"],
                state=initial_state, 
                expected_artifacts=t_def["expected_artifacts"],
                acceptance_criteria=t_def["acceptance_criteria"],
                dependencies=t_def.get("dependencies", [])
            )
            session.add(task)
    
    logger.info("--- Phase 2: Execution & Verification ---")
    max_iterations = 30
    iteration = 0
    
    while iteration < max_iterations:
        iteration += 1
        await orchestrator.tick()
        
        with db_manager.session_scope() as session:
            active_plan = repo.get_active_plan(session, project_id)
            if not active_plan: break
            active_plan_id = active_plan.id
            
            claimed_tasks = session.query(Task).filter(
                Task.plan_id == active_plan_id,
                Task.state == "CLAIMED"
            ).all()
            
            for task in claimed_tasks:
                logger.info(f"Requesting implementation for task {task.id}...")
                try:
                    result_text = provider.generate("", f"Task {task.id}: {task.description}")
                    data = json.loads(result_text)
                    res_msg = Message(
                        header=MessageHeader(
                            sender="MockWorker",
                            recipient="Engine",
                            message_type=MessageType.TASK_RESULT,
                            plan_id=active_plan_id
                        ),
                        payload={"task_id": task.id, "artifacts": data.get("artifacts", [])}
                    )
                    process_task_message(session, res_msg, task.id, MessageType.TASK_RESULT, project_id, artifact_store_root=repo.artifact_store_root)
                except Exception as e:
                    logger.error(f"Worker communication error for task {task.id}: {e}")
                    task.state = "FAILED"

        with db_manager.session_scope() as session:
            active_plan = repo.get_active_plan(session, project_id)
            if not active_plan: break
            all_tasks = session.query(Task).filter(Task.plan_id == active_plan.id).all()
            if all(t.state == "VERIFIED" for t in all_tasks):
                logger.info("🚀 ALL TASKS VERIFIED! Stability test passed.")
                break
            if any(t.state == "FAILED" for t in all_tasks):
                if scenario == "FAILURE" and any(t.id == "T2" and t.state == "READY" for t in all_tasks):
                    pass 
                if iteration > 20: 
                    logger.info("Max iterations reached. Checking final state...")
                    break
        await asyncio.sleep(0.1)

    with db_manager.session_scope() as session:
        active_plan = repo.get_active_plan(session, project_id)
        tasks = session.query(Task).filter(Task.plan_id == active_plan.id).all()
        for t in tasks:
            logger.info(f"Task {t.id}: {t.state}")

    artifact_dir.cleanup()

if __name__ == "__main__":
    asyncio.run(run_stability_test("Build a simple Python CLI TicTacToe game", "SUCCESS"))
    asyncio.run(run_stability_test("Build a simple Python CLI TicTacToe game", "FAILURE"))
