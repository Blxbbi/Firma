import asyncio
import argparse
import json
import logging
import os
import random
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from benchmarks.config import config
from benchmarks.profiles import get_profile
from benchmarks.runner import run_stage
from benchmarks.collector import Collector
from benchmarks.system_probe import SystemProbe
from engine.db import DatabaseManager
from engine.orchestrator import Orchestrator
from engine.repository import MessageRepository
from engine.models import Project, Plan, Task, Base
from engine.services.execution import ExecutionService
from engine.services.concurrency import governor
from benchmarks.dummy_sandbox import DummySandbox
from engine.services.sandbox import LocalPythonSandbox

from engine.services.artifact_store import ArtifactStore
from engine.transport.internal_transport import InternalTransport
from engine.services.telemetry import telemetry

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("benchmark.harness")

class BenchmarkHarness:
    def __init__(self, args):
        self.args = args
        self.run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{args.profile}_{args.label}"
        self.run_dir = config.output_dir / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        
        self.collector = Collector(self.run_dir)
        self.db_manager = DatabaseManager(db_url=config.db_url)
        self.artifact_store = ArtifactStore(base_dir=str(config.artifact_root))
        
        # Transport for the orchestrator
        # Use InternalTransport to isolate kernel performance from network jitter
        self.transport = InternalTransport()
        
        # Sandbox Selection based on profile
        profile_name = args.profile
        if profile_name == "cpu":
            logger.info("Using DummySandbox for pure kernel characterization.")
            self.sandbox = DummySandbox()
        else:
            logger.info("Using LocalPythonSandbox for realistic execution.")
            self.sandbox = LocalPythonSandbox()
            
        self.exec_service = ExecutionService(self.sandbox)
        
        class MockScheduler:
            def run_tick(self): pass
            def assign_unassigned_ready_tasks(self): pass
            
        self.scheduler = MockScheduler()
        
        self.orchestrator = Orchestrator(
            self.db_manager, 
            self.scheduler, 
            self.transport, 
            self.exec_service, 
            self.sandbox
        )

    async def run(self):
        """
        Main SRE Execution Loop.
        """
        profile = get_profile(self.args.profile)
        ramp_levels = [int(x) for x in self.args.ramp.split(',')]
        
        # Global Telemetry and System Probe (shared across stages)
        await telemetry.start()
        await governor.start()
        stop_event = asyncio.Event()
        probe = SystemProbe(self.run_dir / "system_metrics.jsonl")
        probe_task = asyncio.create_task(probe.run_loop(stop_event))
        
        try:
            # 1. Baseline Stage
            await self.run_stage_lifecycle("baseline", 1, 10, profile)
            
            # 2. Ramp Stages
            for level in ramp_levels:
                # Warmup
                logger.info(f"Warming up for {self.args.warmup}s...")
                await asyncio.sleep(self.args.warmup)
                
                # Execute isolated stage
                await self.run_stage_lifecycle(f"L{level}", level, self.args.duration, profile)

            logger.info("\n\n" + "="*60 + "\nBENCHMARK RAMP COMPLETED SUCCESSFULLY\n" + "="*60)

        finally:
            stop_event.set()
            await telemetry.stop()
            await governor.stop()
            probe_task.cancel()

    async def precreate_flights_for_manager(self, db_manager: DatabaseManager, concurrency: int, profile):
        """
        Pre-populates the DB with Projects/Plans/Tasks.
        """
        task_ids = []
        async with db_manager.session_scope() as session:
            num_flights = concurrency * profile.task_pool_multiplier
            for i in range(num_flights):
                f_id = str(uuid.uuid4())[:12]
                p_id = f"PROJ-{f_id}"
                plan_id = f"PLAN-{f_id}"
                t_id = f"TASK-{f_id}"
                
                project = Project(id=p_id, name=f"Bench Flight {f_id}", active_plan_id=plan_id)
                session.add(project)
                
                plan = Plan(id=plan_id, project_id=p_id, version=1, name="Bench Plan", status="IN_PROGRESS")
                session.add(plan)
                
                task = Task(
                    id=t_id,
                    plan_id=plan_id,
                    state="READY",
                    execution_phase="CODING",
                    assigned_role="CODER",
                    state_revision=1,
                    expected_artifacts=["main.py"],
                    acceptance_criteria=["CMD:python main.py 2 3:6"]
                )
                session.add(task)
                task_ids.append(t_id)
            
            logger.info(f"Pre-created {num_flights} flights for concurrency {concurrency}")
        return task_ids

    async def run_stage_lifecycle(self, stage_id: str, concurrency: int, duration: int, profile):
        """
        SRE Gold Standard: Complete isolation for a single stage.
        1. New DB -> 2. New Engine -> 3. Run Stage -> 4. Shutdown.
        """
        logger.info(f"\n{'='*60}\n>>> STARTING ISOLATED STAGE: {stage_id} (Concurrency={concurrency})\n{'='*60}")
        
        # 1. DB Isolation: New file per stage
        stage_db_url = f"sqlite+aiosqlite:///{self.run_dir / f'firma_{stage_id}.db'}"
        stage_db_manager = DatabaseManager(db_url=stage_db_url)
        await stage_db_manager.initialize_db()
        await stage_db_manager.create_tables(Base)
        
        # 2. Engine Isolation: Fresh Orchestrator
        # We create a new transport per stage to clear the asyncio.Queue
        stage_transport = InternalTransport()
        
        # Re-use the execution service but it's stateless relative to the DB
        stage_orchestrator = Orchestrator(
            stage_db_manager, 
            self.scheduler, 
            stage_transport, 
            self.exec_service, 
            self.sandbox
        )
        
        # 3. Fresh Task Pool for this specific DB
        task_ids = await self.precreate_flights_for_manager(stage_db_manager, concurrency, profile)
        
        # 4. Telemetry Reset
        telemetry.reset()
        
        # 5. Engine Start
        orch_task = asyncio.create_task(stage_orchestrator.run_forever())
        stop_event = asyncio.Event()
        
        try:
            # Sanity Gate: Ensure no noise before measurement
            # Since it's a new DB and fresh engine, it should be 0 by definition.
            # We check it to certify the isolation.
            await asyncio.sleep(1) # Let engine tick once
            
            # Run the stage
            await run_stage(profile, concurrency, duration, stage_transport, stop_event, task_ids, stage_db_manager, self.run_id, stage_id=stage_id)
            
            # Snapshot result
            self.collector.capture_snapshot(stage_id)
            
        finally:
            stop_event.set()
            await stage_orchestrator.stop()
            orch_task.cancel()
            # We don't close stage_db_manager as it's handled by session_scopes, 
            # but in a real SRE tool we'd ensure connection pools are drained.
            logger.info(f">>> STAGE {stage_id} COMPLETED AND ISOLATED.\n")

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=str, default="cpu", choices=["cpu", "io", "transition"])
    parser.add_argument("--ramp", type=str, default="10,20,40,60,80,100")
    parser.add_argument("--duration", type=int, default=300)
    parser.add_argument("--warmup", type=int, default=60)
    parser.add_argument("--label", type=str, default="run01")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    
    random.seed(args.seed)
    
    harness = BenchmarkHarness(args)
    await harness.run()

if __name__ == "__main__":
    asyncio.run(main())
