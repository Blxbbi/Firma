import asyncio
import logging
import uuid
import os
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

from engine.db import DatabaseManager
from engine.models import Project, Plan, Task, ExecutionPhase, Base
from engine.orchestrator import Orchestrator
from engine.scheduler import Scheduler
from engine.transport.internal_transport import InternalTransport
from engine.services.execution import ExecutionService
from engine.services.sandbox import LocalPythonSandbox
from sqlalchemy import select

# Import Verifiers for Registration
from engine.services.verification_registry import VerificationRegistry
from engine.services.verifiers.csv_verifier import CSVVerifier
from engine.services.verifiers.web_verifier import WebStructuralVerifier

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger("BENCHMARK_RUNNER")

class BenchmarkRunner:
    """
    Industrial Benchmark Runner for Firma.
    Handles a single, isolated run from config to convergence.
    """
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.config = self._load_config()
        
        # Isolation setup
        self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_dir = Path(f"runs/{self.run_id}")
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.run_dir / "run.db"
        
        # Components
        self.db_manager = DatabaseManager(db_url=f"sqlite+aiosqlite:///{self.db_path}")
        self.transport = InternalTransport()
        self.sandbox = LocalPythonSandbox()
        self.execution_service = ExecutionService(sandbox=self.sandbox)
        
        # Register Verifiers
        VerificationRegistry.register("csv", CSVVerifier)
        VerificationRegistry.register("structural_web", WebStructuralVerifier)

    def _load_config(self) -> Dict[str, Any]:
        with open(self.config_path, 'r') as f:
            return json.load(f)

    async def pre_flight_check(self):
        """
        Verifies that the environment is ready before spending LLM tokens.
        """
        logger.info("Running Pre-Flight Checks...")
        
        # 1. API Keys
        if not os.environ.get("NVIDIA_API_KEY"):
            raise RuntimeError("NVIDIA_API_KEY environment variable not set.")
            
        # 2. Verifier available
        v_type = self.config.get("verification")
        VerificationRegistry.get(v_type) # Should not raise ValueError
        
        # 3. DB reachable
        await self.db_manager.initialize_db()
        await self.db_manager.create_tables(Base)
        
        logger.info("✅ Pre-Flight Checks passed.")

    async def run(self):
        await self.pre_flight_check()
        
        # Setup Engine
        async def dispatch_callback(payload):
            envelope = {
                "message_id": str(uuid.uuid4()),
                "timestamp": datetime.now().isoformat(),
                "payload": payload
            }
            await self.transport.dispatch(envelope)

        scheduler = Scheduler(db_manager=self.db_manager, messenger_callback=dispatch_callback)
        orchestrator = Orchestrator(
            db_manager=self.db_manager, 
            scheduler=scheduler, 
            transport=self.transport, 
            execution_service=self.execution_service, 
            sandbox=self.sandbox
        )
        
        # 1. Setup Project & Task
        async with self.db_manager.session_scope() as session:
            project = Project(
                id=str(uuid.uuid4()),
                name=self.config["project_name"],
                status="ACTIVE"
            )
            session.add(project)
            
            plan = Plan(
                id=str(uuid.uuid4()),
                project_id=project.id,
                version=1,
                name=f"{project.name} v1",
                status="ACTIVE"
            )
            session.add(plan)
            project.active_plan_id = plan.id
            
            task = Task(
                id=str(uuid.uuid4()),
                plan_id=plan.id,
                description=self.config["prompt"],
                execution_phase=ExecutionPhase.PLANNING,
                state="READY",
                state_revision=1,
                expected_artifacts=[],
                acceptance_criteria=[]
            )
            session.add(task)
            
            project_id, plan_id, task_id = project.id, plan.id, task.id

        # 2. Setup Workers
        from engine.providers.nvidia_provider import NvidiaProvider
        provider = NvidiaProvider(api_key=os.environ.get("NVIDIA_API_KEY"))
        
        from workers.planner import PlannerWorker
        from workers.executor import ExecutionWorker
        
        planner = PlannerWorker(provider=provider, model_name=self.config["model"])
        executor = ExecutionWorker(provider=provider, model_name=self.config["model"])

        # 3. Loop until convergence
        iteration = 0
        max_iter = self.config.get("max_iterations", 5)
        
        while iteration < max_iter:
            iteration += 1
            logger.info(f"--- ITERATION {iteration} ---")
            
            await scheduler.run_tick()
            
            while True:
                await orchestrator.tick()
                
                async with self.db_manager.session_scope() as session:
                    res = await session.execute(select(Task).filter(Task.id == task_id))
                    t = res.scalars().first()
                    
                    if t.execution_phase == ExecutionPhase.REVIEWING:
                        logger.info("✅ CONVERGENCE REACHED.")
                        return True
                    
                    if t.state == "FAILED" and t.revision >= max_iter:
                        logger.error("❌ FAILED: Max iterations reached.")
                        return False

                    if t.execution_phase == ExecutionPhase.PLANNING:
                        res_msg = await planner.handle_request(project_id, self.config["prompt"])
                        await self.transport.dispatch({
                            "message_id": res_msg.header.message_id,
                            "timestamp": res_msg.header.timestamp.isoformat(),
                            "event": "PLAN_APPROVED",
                            "sender_role": "PLANNER",
                            "state_revision": t.state_revision,
                            "payload": res_msg.payload
                        })
                    elif t.execution_phase == ExecutionPhase.CODING:
                        res_msg = await executor.handle_assignment(project_id, plan_id, task_id, {})
                        await self.transport.dispatch({
                            "message_id": res_msg.header.message_id,
                            "timestamp": res_msg.header.timestamp.isoformat(),
                            "event": "CODE_SUBMITTED",
                            "sender_role": "CODER",
                            "state_revision": t.state_revision,
                            "payload": res_msg.payload
                        })
                    
                    await asyncio.sleep(1)

    async def archive(self):
        """
        Saves the config and final state for reproducibility.
        """
        with open(self.run_dir / "config.json", "w") as f:
            json.dump(self.config, f, indent=2)
        logger.info(f"Run archived at {self.run_dir}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python benchmark_runner.py <config_json>")
        sys.exit(1)
        
    runner = BenchmarkRunner(sys.argv[1])
    try:
        success = asyncio.run(runner.run())
        print(f"Run result: {'SUCCESS' if success else 'FAILURE'}")
    except Exception as e:
        logger.exception(f"Run crashed: {e}")
    finally:
        asyncio.run(runner.archive())
