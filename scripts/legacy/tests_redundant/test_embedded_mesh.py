import asyncio
import json
import uuid
import logging
from datetime import datetime, timezone
from nats.aio.client import Client as NATS
from nats.js.errors import BadRequestError

from engine.db import DatabaseManager
from engine.models import Base, Task, ExecutionPhase, AssignedRole
from engine.repository import MessageRepository
from engine.transport.pimessenger import PiMessengerTransport
from engine.orchestrator import Orchestrator
from engine.services.guardian import GuardianPipeline
from unittest.mock import MagicMock

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger("Phase1A")

async def setup_nats_clean():
    """Resets NATS streams and consumers to a clean state for Phase 1A."""
    logger.info("Cleaning NATS environment...")
    nc = NATS()
    await nc.connect("nats://localhost:4222")
    js = nc.jetstream()

    # Delete streams to start fresh
    for stream in ["TASKS", "RESPONSES"]:
        try:
            await js.delete_stream(stream)
        except Exception:
            pass

    # TASKS Stream: WorkQueue
    await js.add_stream(
        name="TASKS",
        subjects=["tasks.*"],
        retention="workqueue",
        storage="file",
        num_replicas=1,
    )

    # RESPONSES Stream: WorkQueue
    await js.add_stream(
        name="RESPONSES",
        subjects=["kernel.responses"],
        retention="workqueue",
        storage="file",
        num_replicas=1,
    )

    # Kernel Consumer for Responses
    await js.add_consumer(
        stream="RESPONSES",
        durable_name="kernel-consumer",
        ack_policy="explicit",
        ack_wait=30,
        max_deliver=10,
    )
    
    logger.info("NATS Environment Reset Complete.")
    await nc.close()

async def embedded_worker_task(task_id, role):
    """Minimal worker coroutine: Fetch -> Publish -> Ack."""
    logger.info(f"[Worker] Starting embedded worker for role {role}...")
    
    nc = NATS()
    try:
        await nc.connect("nats://localhost:4222")
        js = nc.jetstream()

        subject = f"tasks.{role}"
        sub = await js.pull_subscribe(
            subject=subject,
            durable=f"worker-{role}-embedded",
            stream="TASKS"
        )
        logger.info(f"[Worker] Subscribed to {subject}")

        while True:
            try:
                msgs = await sub.fetch(batch=1, timeout=1.0)
                if not msgs:
                    continue
                for msg in msgs:
                    logger.info(f"[Worker] Fetched dispatch for Task {task_id}")
                    data = json.loads(msg.data.decode())
                    payload = data["payload"]
                    
                    await asyncio.sleep(0.5)
                    
                    response_payload = {
                        "task_id": task_id,
                        "state_revision": payload["state_revision"],
                        "event": "CODE_SUBMITTED" if role == "CODER" else "VERIFY_SUCCESS",
                        "artifacts": {"files": []} if role == "CODER" else None,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                    
                    envelope = {
                        "protocol_version": "1.0",
                        "message_type": "WORKER_RESPONSE",
                        "message_id": str(uuid.uuid4()),
                        "correlation_id": data.get("correlation_id", "unknown"),
                        "sender_id": f"pi-{role.lower()}-embedded",
                        "role": role,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "payload": response_payload
                    }
                    
                    await js.publish("kernel.responses", json.dumps(envelope).encode())
                    logger.info(f"[Worker] Published response to kernel.responses")
                    await msg.ack()
                    logger.info(f"[Worker] Acked dispatch message")
                    return
            except Exception as e:
                if "timeout" in str(e).lower():
                    continue
                logger.error(f"[Worker] loop error: {e}")
                break
    except Exception as e:
        logger.error(f"[Worker] Critical Error: {e}")
    finally:
        await nc.close()

async def kernel_run_roundtrip(task_id):
    """Kernel flow: Inject -> Dispatch -> Poll -> Process."""
    logger.info("[Kernel] Starting roundtrip...")
    
    db_manager = DatabaseManager("sqlite:///mesh_embedded_test.db")
    Base.metadata.create_all(db_manager.engine)
    
    # 1. Separate Transport Instance
    transport = PiMessengerTransport(sender_id="kernel-01")
    await transport.connect()
    
    # 2. Orchestrator Setup
    scheduler = MagicMock()
    scheduler.run_tick = MagicMock()
    scheduler.assign_unassigned_ready_tasks = MagicMock()
    
    execution_service = MagicMock()
    sandbox = MagicMock()
    
    orchestrator = Orchestrator(
        db_manager=db_manager,
        scheduler=scheduler,
        transport=transport,
        execution_service=execution_service,
        sandbox=sandbox
    )
    
    # 3. Inject Task
    with db_manager.session_scope() as session:
        from engine.models import Project, Plan
        project = Project(id="P-1", name="Phase 1A Project")
        session.add(project)
        session.flush()
        plan = Plan(id="PL-1", project_id=project.id, version=1, name="Sanity Plan", status="IN_PROGRESS")
        session.add(plan)
        session.flush()
        project.active_plan_id = plan.id
        task = Task(
            id=task_id,
            plan_id=plan.id,
            description="Sanity Test Task",
            state="READY",
            execution_phase=ExecutionPhase.CODING,
            assigned_role=AssignedRole.CODER,
            state_revision=0,
            expected_artifacts=[],
            acceptance_criteria=[]
        )
        session.add(task)
        session.commit()
    logger.info(f"[Kernel] Task {task_id} injected (CODING, Rev 0) in Plan PL-1")

    # 4. Tick 1: Dispatch
    logger.info("[Kernel] Tick 1: Dispatching...")
    await asyncio.sleep(1) # Ensure worker is subscribed
    dispatch_payload = {
        "task_id": task_id,
        "assigned_role": "CODER",
        "execution_phase": ExecutionPhase.CODING,
        "state_revision": 0,
        "context": {}
    }
    await transport.dispatch(dispatch_payload)
    logger.info(f"[Kernel] Manually dispatched Task {task_id}")
    
    await orchestrator.tick() 
    logger.info("[Kernel] Tick 1 Complete.")

    await asyncio.sleep(2)

    # 5. Tick 2: Poll and Process
    logger.info("[Kernel] Tick 2: Polling for response...")
    await orchestrator.tick()
    logger.info("[Kernel] Tick 2 Complete.")

    # 6. Verify DB state
    with db_manager.session_scope() as session:
        repo = MessageRepository()
        task = repo.get_task_by_id(session, task_id)
        phase = task.execution_phase
        logger.info(f"[Kernel] Final Task State: Phase={phase}, Rev={task.state_revision}")
        
    await transport.close()
    return phase

async def main():
    task_id = "T-EMBED-01"
    try:
        await setup_nats_clean()
        worker_task = asyncio.create_task(embedded_worker_task(task_id, "CODER"))
        final_phase = await kernel_run_roundtrip(task_id)
        await worker_task
        if final_phase == ExecutionPhase.VERIFYING:
            logger.info("✅ PHASE 1A SUCCESS: Task transitioned to VERIFYING")
        else:
            logger.error(f"❌ PHASE 1A FAILURE: Task is in {final_phase}")
    except Exception as e:
        logger.exception(f"Critical Failure during Phase 1A: {e}")

if __name__ == "__main__":
    asyncio.run(main())
