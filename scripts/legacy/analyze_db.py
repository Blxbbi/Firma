import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from engine.models import Task, Plan, Project

async def analyze_clean_run():
    engine = create_async_engine("sqlite+aiosqlite:///firma_run_8_1_clean.db")
    async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with async_session() as session:
        # 1. Check Projects
        res = await session.execute(select(Project))
        projects = res.scalars().all()
        print(f"Projects found: {len(projects)}")
        for p in projects:
            print(f" - Project: {p.name} ({p.id})")

        # 2. Check Plans
        res = await session.execute(select(Plan))
        plans = res.scalars().all()
        print(f"\nPlans found: {len(plans)}")
        for pl in plans:
            print(f" - Plan: {pl.name} (Version: {pl.version}, ID: {pl.id})")

        # 3. Check Tasks
        res = await session.execute(select(Task))
        tasks = res.scalars().all()
        print(f"\nTasks found: {len(tasks)}")
        for t in tasks:
            print(f" - Task {t.id}: Phase={t.execution_phase}, State={t.state}, Attempts={t.attempt_count}")

if __name__ == "__main__":
    asyncio.run(analyze_clean_run())
