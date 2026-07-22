import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

from engine.db import DatabaseManager
from engine.models import Base, Project, Plan, Task
from engine.scheduler import Scheduler
from engine.repository import MessageRepository

async def test_scheduler():
    db_file = "firma_run_9_1_clean.db"
    if os.path.exists(db_file):
        print(f"Removing old DB: {db_file}")
        os.remove(db_file)
    
    db_manager = DatabaseManager(f"sqlite+aiosqlite:///{db_file}")
    await db_manager.initialize_db()
    await db_manager.create_tables(Base)
    
    async with db_manager.session_scope() as session:
        # Setup
        project = Project(name="Test Project")
        session.add(project)
        await session.flush()
        
        plan = Plan(project_id=project.id, name="Test Plan", status="IN_PROGRESS")
        session.add(plan)
        await session.flush()
        
        project.active_plan_id = plan.id
        
        task = Task(
            id="TASK-1",
            plan_id=plan.id,
            state="READY",
            execution_phase="PLANNING",
            assigned_role="PLANNER",
            expected_artifacts=[],
            acceptance_criteria=[]
        )
        session.add(task)
        await session.commit()
        
        print(f"Setup complete. Project: {project.id}, Plan: {plan.id}, Task: {task.id}")

    # Test Scheduler
    scheduler = Scheduler(db_manager)
    
    async with db_manager.session_scope() as session:
        repo = MessageRepository(session)
        # Use the same logic as Scheduler._handle_assignments
        proj_res = await session.execute(select(Project).limit(1))
        project = proj_res.scalars().first()
        active_plan_id = project.active_plan_id
        
        ready_tasks = await repo.get_unassigned_ready_tasks(session, active_plan_id)
        print(f"Scheduler found {len(ready_tasks)} ready tasks.")
        
        if len(ready_tasks) > 0:
            print(f"Found task: {ready_tasks[0].id}, State: {ready_tasks[0].state}")
        else:
            print("FAILED: Scheduler found no tasks!")

if __name__ == "__main__":
    asyncio.run(test_scheduler())
