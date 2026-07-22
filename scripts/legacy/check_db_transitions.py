import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

async def check_db(db_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    
    async with async_session() as session:
        result = await session.execute(text("SELECT count(*) FROM task_transition_log;"))
        count = result.scalar()
        print(f"Transitions in {db_path}: {count}")

if __name__ == "__main__":
    import sys
    path = sys.argv[1]
    asyncio.run(check_db(path))
