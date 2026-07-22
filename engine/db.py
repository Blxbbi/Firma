import logging
import asyncio
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text

logger = logging.getLogger(__name__)

class DatabaseManager:
    """
    Central Database Manager implementing the Async Unit-of-Work pattern.
    
    Ensures that sessions are isolated, short-lived, and transacted correctly.
    """
    def __init__(self, db_url: str = "sqlite+aiosqlite:///firma.db"):
        # Use async engine
        self.engine = create_async_engine(
            db_url, 
            echo=False,
            # For SQLite async, we don't need check_same_thread as much but good to keep
            connect_args={"check_same_thread": False} 
        )
        
        # Async Session factory
        self.AsyncSessionLocal = async_sessionmaker(
            bind=self.engine, 
            expire_on_commit=False, # Crucial: prevent DetachedInstanceError in async
            autoflush=False,
            class_=AsyncSession
        )

    async def initialize_db(self):
        """
        Enable WAL mode for SQLite and other optimizations.
        """
        if "sqlite" in self.engine.url.drivername:
            async with self.engine.begin() as conn:
                await conn.execute(text("PRAGMA journal_mode=WAL;"))
                await conn.execute(text("PRAGMA synchronous=NORMAL;"))

    @asynccontextmanager
    async def session_scope(self):
        """
        Provide a transactional scope around a series of operations.
        Commits automatically if no exception occurs.
        """
        async with self.AsyncSessionLocal() as session:
            async with session.begin():
                try:
                    yield session
                except Exception as e:
                    # session.begin() context manager handles rollback automatically
                    logger.error(f"Async session scope encountered error: {str(e)}")
                    raise

    async def create_tables(self, base):
        """
        Initializes the database schema asynchronously.
        """
        async with self.engine.begin() as conn:
            # Note: base.metadata.create_all is sync. 
            # We run it in a thread or use the async equivalent if available.
            # For most setups, run_sync is the standard way to handle metadata.create_all.
            await conn.run_sync(base.metadata.create_all)
