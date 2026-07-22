import asyncio
import logging
import uuid
import os
from datetime import datetime

from engine.db import DatabaseManager
from engine.models import Project, Plan, Task, ExecutionPhase, Base
from engine.orchestrator import Orchestrator
from engine.scheduler import Scheduler
from engine.transport.internal_transport import InternalTransport
from engine.services.execution import ExecutionService
from engine.services.sandbox import LocalPythonSandbox
from sqlalchemy import select

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger("RUN_SNAKE")

# --- CONFIGURATION ---
USER_PROMPT = """
Projekt: "Neon-Snake Industrial Edition"

Ziel: Erstelle ein vollständig funktionsfähiges, browserbasiertes Snake-Spiel. Das Spiel soll in einer einzigen HTML-Datei (inklusive CSS und JS) oder einer sauberen Trennung (index.html, style.css, script.js) geliefert werden.

Funktionale Anforderungen:
1. Core Gameplay: Klassisches Snake-Prinzip. Die Schlange bewegt sich in einem Raster, frisst Nahrung, wächst und das Spiel endet bei Kollision mit den Wänden oder dem eigenen Körper.
2. Geschwindigkeitssteuerung: Implementiere ein Interface (z. B. Radio-Buttons oder ein Dropdown), mit dem der Spieler zwischen drei Geschwindigkeiten wählen kann:
   - Slow (für Anfänger)
   - Normal (Standard)
   - Fast (für Profis)
   Die Geschwindigkeit muss den Takt des Game-Loops direkt beeinflussen.
3. UI/UX:
   - Ein prominenter Score-Zähler.
   - Ein „Start/Restart“-Button, um das Spiel zu beginnen oder nach einem Game-Over neu zu starten.
   - Anzeige des aktuell gewählten Geschwindigkeitsmodus.

Visueller Stil:
- Look: "Modern-Classic / Neon". Dunkler Hintergrund (Dark Mode), leuchtende Farben für die Schlange und die Nahrung (Glow-Effekte).
- Feeling: Das Spiel soll „cool“ und poliert aussehen, aber die Spielmechanik absolut klassisch bleiben (keine diagonalen Bewegungen, striktes Raster).

Technische Constraints:
- Verwende HTML5 Canvas für das Rendering.
- Der Code muss robust sein (keine Fehler in der Browser-Konsole).
- Das Spiel muss direkt durch Öffnen der HTML-Datei im Browser spielbar sein.
"""

DB_PATH = "firma_snake.db"
MAX_ITERATIONS = 5

async def main():
    # 1. Setup Infrastructure
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        
    db_manager = DatabaseManager(db_url=f"sqlite+aiosqlite:///{DB_PATH}")
    await db_manager.initialize_db()
    await db_manager.create_tables(Base)
    
    transport = InternalTransport()
    
    # The scheduler needs a callback to send messages.
    # We use transport.dispatch as the callback.
    async def dispatch_callback(payload):
        # Wrap payload in a basic envelope to avoid crashes in transport
        envelope = {
            "message_id": str(uuid.uuid4()),
            "timestamp": datetime.now().isoformat(),
            "payload": payload
        }
        await transport.dispatch(envelope)

    scheduler = Scheduler(db_manager=db_manager, messenger_callback=dispatch_callback)
    sandbox = LocalPythonSandbox()
    execution_service = ExecutionService(sandbox=sandbox)
    
    orchestrator = Orchestrator(
        db_manager=db_manager, 
        scheduler=scheduler, 
        transport=transport, 
        execution_service=execution_service, 
        sandbox=sandbox
    )
    
    # 2. Create Project and Initial Task
    async with db_manager.session_scope() as session:
        project = Project(
            id=str(uuid.uuid4()),
            name="Neon-Snake",
            status="ACTIVE",
            active_plan_id=None # Set this after plan is created
        )
        session.add(project)
        
        plan = Plan(
            id=str(uuid.uuid4()),
            project_id=project.id,
            version=1,
            name="Neon-Snake v1",
            status="ACTIVE"
        )
        session.add(plan)
        
        # Important: Link active plan to project for the Scheduler
        project.active_plan_id = plan.id
        
        task = Task(
            id=str(uuid.uuid4()),
            plan_id=plan.id,
            description="Implement the Neon-Snake game based on the project goal.",
            execution_phase=ExecutionPhase.PLANNING,
            state="READY",
            state_revision=1,
            expected_artifacts=[],
            acceptance_criteria=[]
        )
        session.add(task)
        
        project_id, plan_id, task_id = project.id, plan.id, task.id

    logger.info(f"🚀 STARTING SNAKE RUN - Project: {project_id}")

    from engine.providers.nvidia_provider import NvidiaProvider
    provider = NvidiaProvider(api_key=os.environ.get("NVIDIA_API_KEY"))
    
    planner = PlannerWorker(provider=provider, model_name="meta/llama-3.1-70b-instruct")
    executor = ExecutionWorker(provider=provider, model_name="meta/llama-3.1-70b-instruct")

    iteration = 0
    while iteration < MAX_ITERATIONS:
        iteration += 1
        logger.info(f"--- ITERATION {iteration} ---")
        
        # Trigger a scheduler tick to assign the task
        await scheduler.run_tick()
        
        while True:
            await orchestrator.poll_dispatch()
            
            async with db_manager.session_scope() as session:
                res = await session.execute(select(Task).filter(Task.id == task_id))
                t = res.scalars().first()
                
                if t.phase == ExecutionPhase.REVIEWING:
                    logger.info("✅ CONVERGENCE REACHED: Task is in REVIEWING phase.")
                    return
                
                if t.status == "FAILED" and t.revision >= MAX_ITERATIONS:
                    logger.error("❌ FAILED: Max iterations reached.")
                    return

                if t.phase == ExecutionPhase.PLANNING:
                    # Planner: handle_request(project_id, user_prompt)
                    res = await planner.handle_request(project_id, USER_PROMPT)
                    await transport.dispatch({
                        "message_id": res.header.message_id,
                        "timestamp": res.header.timestamp.isoformat(),
                        "event": "PLAN_APPROVED", # Simulate approval for the loop
                        "sender_role": "PLANNER",
                        "state_revision": t.state_revision,
                        "payload": res.payload
                    })
                elif t.phase == ExecutionPhase.CODING:
                    # Executor: handle_assignment(project_id, plan_id, task_id, task_def)
                    # We pass empty dict for task_def as it's a simple run
                    res = await executor.handle_assignment(project_id, plan_id, task_id, {})
                    await transport.dispatch({
                        "message_id": res.header.message_id,
                        "timestamp": res.header.timestamp.isoformat(),
                        "event": "CODE_SUBMITTED",
                        "sender_role": "CODER",
                        "state_revision": t.state_revision,
                        "payload": res.payload
                    })
                elif t.phase == ExecutionPhase.VERIFYING:
                    pass
                
                await asyncio.sleep(1)
                
    logger.warning("⚠️ Loop finished without reaching REVIEWING phase.")

if __name__ == "__main__":
    asyncio.run(main())
