import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from engine.db import DatabaseManager
from engine.models import Project, Plan, Task

async def diagnose():
    db_url = "sqlite+aiosqlite:///firma_run_9_1_final_test.db"
    engine = create_async_engine(db_url)
    async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with async_session() as session:
        print("--- Diagnosing firma_run_9_1_final_test.db ---")
        
        # Check Projects
        proj_res = await session.execute(select(Project))
        projects = proj_res.scalars().all()
        print(f"Projects found: {len(projects)}")
        for p in projects:
            print(f" Project: {p.id}, Name: {p.name}, Active Plan: {p.active_plan_id}")

        # Check Plans
        plan_res = await session.execute(select(Plan))
        plans = plan_res.scalars().all()
        print(f"Plans found: {len(plans)}")
        for pl in plans:
            print(f" Plan: {pl.id}, Project: {pl.project_id}, Status: {pl.status}")

        # Check Tasks
        task_res = await session.execute(select(Task))
        tasks = task_res.scalars().all()
        print(f"Tasks found: {len(tasks)}")
        for t in tasks:
            print(f" Task: {t.id}, Plan: {t.plan_id}, State: {repr(t.state)}, Phase: {repr(t.execution_phase)}, Worker: {repr(t.assigned_worker)}")

if __name__ == "__main__":
    asyncio.run(diagnose())
