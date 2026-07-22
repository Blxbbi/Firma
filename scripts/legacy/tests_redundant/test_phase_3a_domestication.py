import asyncio
import json
import os
import subprocess
import uuid
import logging
from datetime import datetime, timezone
from typing import Tuple, Optional

from nats.aio.client import Client as NATS
from engine.db import DatabaseManager
from engine.models import Base, Task, ExecutionPhase, AssignedRole, TaskEvent, TaskTransitionLog, Project, Plan
from engine.repository import MessageRepository
from engine.orchestrator import Orchestrator
from engine.transport.pimessenger import PiMessengerTransport
from pydantic import BaseModel

# Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] 3A-Domestication: %(message)s'
)
logger = logging.getLogger("DomesticationTest")

class StateSnapshot(BaseModel):
    phase: ExecutionPhase
    role: Optional[AssignedRole]
    revision: int
    transitions: int

async def get_snapshot(session, task_id):
    repo = MessageRepository()
    task = repo.get_task_by_id(session, task_id)
    trans_count = session.query(TaskTransitionLog).filter(TaskTransitionLog.task_id == task_id).count()
    return StateSnapshot(
        phase=ExecutionPhase(task.execution_phase),
        role=AssignedRole(task.assigned_role) if task.assigned_role else None,
        revision=task.state_revision,
        transitions=trans_count
    )

async def run_domestication_test():
    """
    Phase 3A Domestication Test Harness.
    Proves that probabilistic LLM workers cannot corrupt the deterministic kernel.
    """
    logger.info("--- STARTING PHASE 3A DOMESTICATION VALIDATION ---")
    
    db_url = "sqlite:///mesh_domestication.db"
    
    # Initial Clean: Remove DB BEFORE creating DatabaseManager to avoid lock
    if os.path.exists("mesh_domestication.db"):
        try:
            os.remove("mesh_domestication.db")
        except PermissionError:
            logger.warning("Could not remove DB file (likely locked). Proceeding anyway.")
            
    db_manager = DatabaseManager(db_url)
    Base.metadata.create_all(db_manager.engine)
    
    transport = PiMessengerTransport(nats_url="nats://localhost:4222")
    await transport.connect()
    
    class MockScheduler:
        def __init__(self, db_manager, transport):
            self.db = db_manager
            self.transport = transport

        async def assign_unassigned_ready_tasks(self):
            with self.db.session_scope() as session:
                from engine.repository import MessageRepository
                repo = MessageRepository()
                tasks = repo.get_unassigned_ready_tasks(session)
                for task in tasks:
                    logger.info(f"[MockScheduler] Dispatching task {task.id} to {task.assigned_role}")
                    await self.transport.dispatch({
                        "task_id": task.id,
                        "assigned_role": task.assigned_role,
                        "execution_phase": task.execution_phase,
                        "state_revision": task.state_revision,
                        "description": task.description,
                        "acceptance_criteria": task.acceptance_criteria,
                        "existing_artifacts": [],
                        "allowed_events": ["CODE_SUBMITTED"]
                    })
                    task.state = 'CLAIMED'
                    session.commit()

    class MockExecutionService: pass
    class MockSandbox: pass
    
    orchestrator = Orchestrator(
        db_manager=db_manager, 
        scheduler=MockScheduler(db_manager, transport), 
        transport=transport, 
        execution_service=MockExecutionService(), 
        sandbox=MockSandbox()
    )
    
    orchestrator_task = asyncio.create_task(orchestrator.run_forever())
    await asyncio.sleep(1)

    async def setup_task():
        # Unique IDs for every sub-test to avoid IntegrityErrors
        current_task_id = f"T-DOMEST-{uuid.uuid4().hex[:6]}"
        with db_manager.session_scope() as session:
            p_id = f"P-DOMEST-{uuid.uuid4().hex[:6]}"
            pl_id = f"PL-DOMEST-{uuid.uuid4().hex[:6]}"
            project = Project(id=p_id, name="Domestication Project")
            session.add(project)
            session.flush()
            plan = Plan(id=pl_id, project_id=project.id, version=1, name="Dom Plan", status="IN_PROGRESS")
            session.add(plan)
            session.flush()
            project.active_plan_id = plan.id
            task = Task(
                id=current_task_id, 
                plan_id=plan.id, 
                state="READY", 
                execution_phase=ExecutionPhase.CODING, 
                assigned_role=AssignedRole.CODER, 
                state_revision=0, 
                expected_artifacts=[], 
                acceptance_criteria=[]
            )
            session.add(task)
            session.commit()
        return current_task_id

    async def cleanup_nats():
        await asyncio.sleep(0.5)

    def spawn_worker(mode: str):
        env = os.environ.copy()
        env["LLM_MODE"] = mode
        env["USE_REAL_LLM"] = "false"
        # Redirect to file for easier debugging
        log_file = open(f"worker_{mode}.log", "w")
        return subprocess.Popen(
            ["python3", "pi_coder_llm.py"], 
            env=env, 
            stdout=log_file, 
            stderr=log_file
        )

    try:
        # -------------------------------------------------------------------------
        # TEST CASE 1: BROKEN_JSON (Worker-Level Domestizierung)
        # -------------------------------------------------------------------------
        logger.info("\n[TEST 1] Scenario: BROKEN_JSON")
        task_id = await setup_task()
        await cleanup_nats()
        
        monitor_nc = NATS()
        await monitor_nc.connect("nats://localhost:4222")
        monitor_sub = await monitor_nc.subscribe("kernel.responses")
        
        worker = spawn_worker("BROKEN_JSON")
        await asyncio.sleep(3) 
        
        try:
            msg = await monitor_sub.next_msg(timeout=1.0)
            if msg:
                logger.error(f"❌ FAILURE: Worker published broken JSON to NATS: {msg.data}")
        except Exception as e:
            if "timeout" in str(e).lower():
                logger.info("✅ SUCCESS: Worker blocked invalid JSON internally. No NATS publish.")
            else:
                logger.error(f"Unexpected error during monitor: {e}")
                raise e

        with db_manager.session_scope() as session:
            state = await get_snapshot(session, task_id)
            logger.info(f"DB State: {state}")
            assert state.revision == 0
        
        worker.terminate()
        await monitor_nc.close()

        # -------------------------------------------------------------------------
        # TEST CASE 2: EVENT_HIJACK (Kernel-Level Immunität)
        # -------------------------------------------------------------------------
        logger.info("\n[TEST 2] Scenario: EVENT_HIJACK")
        task_id = await setup_task()
        await cleanup_nats()
        
        worker = spawn_worker("EVENT_HIJACK")
        await asyncio.sleep(3)
        
        with db_manager.session_scope() as session:
            state = await get_snapshot(session, task_id)
            logger.info(f"DB State: {state}")
            assert state.revision == 0
        
        worker.terminate()

        # -------------------------------------------------------------------------
        # TEST CASE 3: BAD_CODE (Functional Regression)
        # -------------------------------------------------------------------------
        logger.info("\n[TEST 3] Scenario: BAD_CODE (Regression Loop)")
        task_id = await setup_task()
        await cleanup_nats()
        
        worker = spawn_worker("BAD_CODE")
        await asyncio.sleep(3)
        
        with db_manager.session_scope() as session:
            state = await get_snapshot(session, task_id)
            logger.info(f"State after submission: {state}")
            assert state.phase == ExecutionPhase.VERIFYING
            assert state.revision == 1
        
        worker.terminate()
        
        logger.info("Simulating Sandbox Failure...")
        nc_sys = NATS()
        await nc_sys.connect("nats://localhost:4222")
        js_sys = nc_sys.jetstream()
        
        payload = {
            "protocol_version": "1.0",
            "message_id": str(uuid.uuid4()),
            "task_id": task_id,
            "state_revision": 1,
            "event": "VERIFY_FAILURE",
            "sender_role": "SYSTEM",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "artifacts": {},
            "logs": "Tests failed: SyntaxError in main.py"
        }
        envelope = {
            "protocol_version": "1.0",
            "message_type": "WORKER_RESPONSE",
            "message_id": payload["message_id"],
            "role": "SYSTEM",
            "payload": payload,
            "timestamp": payload["timestamp"]
        }
        await js_sys.publish("kernel.responses", json.dumps(envelope).encode())
        await asyncio.sleep(1)
        
        with db_manager.session_scope() as session:
            state = await get_snapshot(session, task_id)
            logger.info(f"State after failure: {state}")
            assert state.phase == ExecutionPhase.CODING
            assert state.revision == 2
            assert state.role == AssignedRole.CODER
            
        await nc_sys.close()

        # -------------------------------------------------------------------------
        # TEST CASE 4: HAPPY (End-to-End)
        # -------------------------------------------------------------------------
        logger.info("\n[TEST 4] Scenario: HAPPY PATH")
        task_id = await setup_task()
        await cleanup_nats()
        
        worker = spawn_worker("HAPPY")
        await asyncio.sleep(3)
        
        nc_sys = NATS()
        await nc_sys.connect("nats://localhost:4222")
        js_sys = nc_sys.jetstream()
        
        with db_manager.session_scope() as session:
            rev = (await get_snapshot(session, task_id)).revision
            
        # 1. System verifies success
        payload = {
            "protocol_version": "1.0",
            "message_id": str(uuid.uuid4()),
            "task_id": task_id,
            "state_revision": rev,
            "event": "VERIFY_SUCCESS",
            "sender_role": "SYSTEM",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "artifacts": {},
        }
        envelope = {
            "protocol_version": "1.0",
            "message_type": "WORKER_RESPONSE",
            "message_id": payload["message_id"],
            "role": "SYSTEM",
            "payload": payload,
            "timestamp": payload["timestamp"]
        }
        await js_sys.publish("kernel.responses", json.dumps(envelope).encode())
        await asyncio.sleep(1)
        
        with db_manager.session_scope() as session:
            rev = (await get_snapshot(session, task_id)).revision
            
        # 2. Reviewer approves
        payload = {
            "protocol_version": "1.0",
            "message_id": str(uuid.uuid4()),
            "task_id": task_id,
            "state_revision": rev,
            "event": "REVIEW_APPROVED",
            "sender_role": "REVIEWER",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "artifacts": {},
        }
        envelope = {
            "protocol_version": "1.0",
            "message_type": "WORKER_RESPONSE",
            "message_id": payload["message_id"],
            "role": "REVIEWER",
            "payload": payload,
            "timestamp": payload["timestamp"]
        }
        await js_sys.publish("kernel.responses", json.dumps(envelope).encode())
        await asyncio.sleep(1)
        
        with db_manager.session_scope() as session:
            final_state = await get_snapshot(session, task_id)
            logger.info(f"Final State: {final_state}")
            assert final_state.phase == ExecutionPhase.COMPLETE
            assert final_state.role is None
            assert final_state.revision == 3
            
            logs = session.query(TaskTransitionLog).filter(TaskTransitionLog.task_id == task_id).all()
            logger.info("\n--- FINAL TRANSITION LOG DUMP ---")
            for l in logs:
                logger.info(f"Rev {l.previous_revision}->{l.new_revision} | {l.from_phase} --({l.event})--> {l.to_phase} | Role: {l.sender_role}")
            logger.info("--------------------------------\n")

        worker.terminate()
        await nc_sys.close()
        logger.info("✅ PHASE 3A DOMESTICATION VERIFIED: Probabilistic outputs are strictly controlled.")

    finally:
        orchestrator_task.cancel()
        await transport.close()

if __name__ == "__main__":
    asyncio.run(run_domestication_test())
