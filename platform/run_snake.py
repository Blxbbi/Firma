import asyncio
import os
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from engine.db import DatabaseManager
from engine.controller import RunController
from engine.orchestrator import Orchestrator
from engine.scheduler import Scheduler
from engine.transport.internal_transport import InternalTransport
from engine.services.execution import ExecutionService
from engine.services.sandbox import LocalPythonSandbox
from engine.services.verification_registry import VerificationRegistry
from engine.services.verifiers.web_verifier import WebStructuralVerifier
from engine.providers.nvidia_provider import NvidiaProvider
from engine.providers.pi_provider import PiProvider
from engine.models import Message, MessageType, TaskEvent
from workers.planner import PlannerWorker
from workers.executor import ExecutionWorker
from engine.settings import DB_DIR, BASE_DIR, FIRMA_TRANSPORT, PIMESH_CREWS, PIMESH_MODELS

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger("SNAKE_RUN")

async def run_worker_sim(run_id: str, transport: InternalTransport, planner: PlannerWorker, executor: ExecutionWorker):
    """
    Simulates a worker harness that consumes tasks from the transport and routes them to workers.
    """
    logger.info(f"Worker Simulator started for run {run_id}...")
    try:
        while True:
            msg = await transport.get_dispatch()
            logger.info(f"[WorkerSim] SQUAWK: payload received: {msg}")
            if not msg:
                await asyncio.sleep(0.1)
                continue

            if msg.get("event") != "TASK_ASSIGNMENT":
                continue

            task_id = msg.get("task_id")
            role = msg.get("role")
            prompt = msg.get("prompt")
            logger.info(f"[WorkerSim] Processing {role} task {task_id}")

            try:
                if role == "PLANNER":
                    response = await planner.handle_request(project_id=run_id, user_prompt=prompt, task_id=task_id)
                elif role == "CODER":
                    project_id = msg.get("project_id", run_id)
                    plan_id = msg.get("plan_id", "default-plan")
                    task_def = msg.get("task_definition", {})
                    global_goal = msg.get("prompt", "")
                    response = await executor.handle_assignment(
                        project_id=project_id,
                        plan_id=plan_id,
                        task_id=task_id,
                        task_definition=task_def,
                        global_goal=global_goal
                    )
                elif role == "REVIEWER":
                    # Happy-Path Simulation: Auto-approve review tasks
                    logger.info(f"[WorkerSim] Simulating REVIEWER approval for task {task_id}")
                    payload_to_send = {
                        "project_id": msg.get("project_id", run_id),
                        "run_id": msg.get("project_id", run_id),
                        "task_id": task_id,
                        "event": "REVIEW_APPROVED",
                        "sender_role": "REVIEWER",
                        "logs": "Review approved (simulated happy-path).",
                        "state_revision": msg.get("state_revision")
                    }
                    await transport.publish_response(role=role, payload=payload_to_send)
                    logger.info(f"[WorkerSim] Review approval sent for task {task_id}")
                    continue
                else:
                    logger.warning(f"Unknown role {role}, skipping.")
                    continue

                # Use publish_response for Worker -> Engine communication
                # We send only the payload part of the Message object, and inject state_revision
                payload_to_send = response.payload if hasattr(response, 'payload') else response
                if isinstance(payload_to_send, dict):
                    payload_to_send["state_revision"] = msg.get("state_revision")
                    payload_to_send["run_id"] = msg.get("project_id", run_id)
                
                await transport.publish_response(
                    role=role, 
                    payload=payload_to_send
                )
                logger.info(f"[WorkerSim] Response sent for task {task_id}")

            except Exception as e:
                logger.error(f"[WorkerSim] Error executing task {task_id}: {e}")
                fail_payload = {
                    "event": "TASK_FAILED", 
                    "error_code": "WORKER_EXCEPTION", 
                    "detail": str(e),
                    "task_id": task_id,
                    "sender_role": role,
                    "run_id": msg.get("project_id", run_id),
                    "state_revision": msg.get("state_revision")
                }
                await transport.publish_response(role=role, payload=fail_payload)
                logger.info(f"[WorkerSim] Error response published for task {task_id}")

    except asyncio.CancelledError:
        logger.info("Worker Simulator shutting down...")

async def main_logic():
    # --- PLATFORM BOOTSTRAP ---
    # Register required verifiers for this run
    VerificationRegistry.register("structural_web", WebStructuralVerifier)
    
    db_path = DB_DIR / f"snake_run_{os.getpid()}.db"
    if db_path.exists(): os.remove(db_path)
    
    db_manager = DatabaseManager(f"sqlite+aiosqlite:///{db_path}")
    from engine.models import Base
    async with db_manager.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    def scheduler_factory(db, messenger_callback):
        return Scheduler(db, messenger_callback=messenger_callback)
    def transport_factory():
        return InternalTransport()
    
    execution_service = ExecutionService(db_manager)
    sandbox = LocalPythonSandbox()

    controller = RunController(
        db_manager=db_manager,
        scheduler_factory=scheduler_factory,
        transport_factory=transport_factory,
        execution_service=execution_service,
        sandbox=sandbox
    )

    config = _select_config()

    logger.info("🚀 Starting Validation Run...")
    run_id = await controller.create_run(config)
    
    provider = NvidiaProvider(api_key="REDACTED_NVIDIA_KEY")
    planner = PlannerWorker(provider=provider, model_name="meta/llama-3.1-70b-instruct")
    executor = ExecutionWorker(provider=provider, model_name="meta/llama-3.1-70b-instruct")
    
    receiver_task = None
    worker_task = None
    if FIRMA_TRANSPORT == "pimesh":
        from engine.transport.pi_mesh_transport import PiMeshTransport
        from run_pi_mesh import PiMeshReceiverLoop, make_pimesh_messenger_callback
        shared_transport = PiMeshTransport(crew_cwds=PIMESH_CREWS, project_root=str(BASE_DIR))
        controller.transport_factory = lambda: shared_transport
        # Single authority: Scheduler CLAIM (READY->CLAIMED) -> dispatch + PiProvider-Spawn
        pi_provider = PiProvider()
        pimesh_callback, _spawned = make_pimesh_messenger_callback(
            transport=shared_transport,
            provider=pi_provider,
            crew_cwds=PIMESH_CREWS,
            project_root=str(BASE_DIR),
            models=PIMESH_MODELS,
        )
        await controller.start_run(run_id, messenger_callback=pimesh_callback)
        receiver = PiMeshReceiverLoop(
            transport=shared_transport,
            crew_cwds=PIMESH_CREWS,
            project_root=str(BASE_DIR),
            expected_run_id=run_id,
        )
        if os.environ.get("FIRMA_DEBUG_RECEIVER_RECOVERY") == "1":
            for role, cwd in PIMESH_CREWS.items():
                worker_dir = receiver._worker_dir(cwd)
                logger.info(
                    '[Receiver-Path] role=%s crew_cwd=%s worker_dir=%s run_id=%s',
                    role, cwd, worker_dir, run_id,
                )
        receiver_task = asyncio.create_task(receiver.run())
        logger.info("🔗 PiMesh mode: transport=PiMeshTransport + PiProvider spawn; WorkerSim disabled.")
    else:
        shared_transport = InternalTransport()
        controller.transport_factory = lambda: shared_transport
        await controller.start_run(run_id)
        worker_task = asyncio.create_task(run_worker_sim(run_id, shared_transport, planner, executor))

    try:
        last_status = None
        while True:
            status_info = await controller.get_run_status(run_id)
            status = status_info["status"]
            
            if status != last_status:
                logger.info(f"🌟 [RUN STATUS UPDATE] {status} | Metrics: {status_info['metrics']}")
                last_status = status
            
            if status in ["COMPLETED", "FAILED", "CANCELLED"]:
                logger.info(f"🏁 Run reached terminal state: {status}")
                break
            
            await asyncio.sleep(5)
    finally:
        if worker_task:
            worker_task.cancel()
        if receiver_task:
            receiver_task.cancel()
        await controller.stop_run(run_id)
        logger.info("✅ Snake Run finished.")

def _select_config():
    app = os.environ.get("FIRMA_APP", "snake").lower()
    if app == "counter":
        return _counter_config()
    return _snake_config()


def _snake_config():
    return {
        "project_name": "Retro Snake Game",
        "plan_name": "Classic Snake Implementation",
        "prompt": (
            "You are an expert web developer. Create a fully functional, retro-style Snake game as a web app.\n\n"
            "CRITICAL DELIVERY REQUIREMENTS:\n"
            "1. You MUST produce exactly these three files:\n"
            "   - index.html (The main page containing the game canvas)\n"
            "   - style.css (Retro arcade aesthetics: dark background, neon colors, pixel font)\n"
            "   - game.js (Complete game logic: movement, food growth, collision detection, scoring)\n"
            "2. No Python files. No requirements.txt. No explanations. No markdown text outside the JSON.\n"
            "3. The game must be immediately playable in a browser.\n"
            "4. Use HTML5 Canvas for the game board.\n"
            "5. Implement classic snake mechanics: arrow keys for movement, eating food to grow, game over on wall/self collision.\n"
            "6. Ensure a responsive layout that centers the game board.\n\n"
            "You work FILE-BASED: write the three files (index.html, style.css, game.js) directly "
            "into your task working directory. Do NOT return JSON in your chat/STDOUT \u2014 the files "
            "on disk are the deliverable."
        ),
        "expected_artifacts": ["index.html", "style.css", "game.js"],
        "acceptance_criteria": [
            "EXISTS:index.html",
            "EXISTS:style.css",
            "EXISTS:game.js",
            "CONTAINS:index.html:<canvas",
            "CONTAINS:game.js:requestAnimationFrame",
            "CONTAINS:game.js:addEventListener('keydown'"
        ],
        "verification_type": "structural_web",
    }


def _counter_config():
    """Phase 5.1 — kleines Web-Artefakt (Button + Counter), kein Game-Loop."""
    return {
        "project_name": "Counter Web App",
        "plan_name": "Single-Page Counter Implementation",
        "prompt": (
            "You are an expert web developer. Build a single-page counter web app (no frameworks).\n\n"
            "CRITICAL DELIVERY REQUIREMENTS:\n"
            "1. Produce exactly these three files:\n"
            "   - index.html (page with a heading, a count display, and a button labeled 'Increment')\n"
            "   - style.css (clean, centered layout)\n"
            "   - app.js (a counter variable; the button's click handler increments it and updates the display)\n"
            "2. No build tools, no external libraries. Plain HTML/CSS/JS.\n"
            "3. The app must work by opening index.html in a browser.\n\n"
            "You work FILE-BASED: write the files described in your task assignment directly into "
            "your task working directory. Do NOT return JSON in your chat/STDOUT \u2014 the files on disk "
            "are the deliverable."
        ),
        "expected_artifacts": ["index.html", "style.css", "app.js"],
        "acceptance_criteria": [
            "EXISTS:index.html",
            "EXISTS:style.css",
            "EXISTS:app.js",
            "CONTAINS:index.html:<button",
            "CONTAINS:app.js:addEventListener",
            "CONTAINS:app.js:innerHTML",
        ],
        "verification_type": "structural_web",
    }


async def main():
    try:
        await asyncio.wait_for(main_logic(), timeout=1200)
    except asyncio.TimeoutError:
        logger.error("❌ Run timed out after 1200 seconds.")
    except Exception as e:
        logger.exception(f"Critical error during run: {e}")

if __name__ == "__main__":
    asyncio.run(main())
