import unittest
import asyncio
import os
import uuid
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from engine.models import Base, Plan, Task, Artifact
from engine.repository import MessageRepository


class TestRepoArtifactDedupTaskScoped(unittest.TestCase):
    def setUp(self):
        self.db_file = f"test_repo_dedup_{uuid.uuid4()}.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_file}")
        self.session_maker = sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

    def tearDown(self):
        if hasattr(self, 'engine') and self.engine:
            try:
                asyncio.get_event_loop().run_until_complete(self.engine.dispose())
            except Exception:
                pass
        if hasattr(self, 'db_file') and os.path.exists(self.db_file):
            try:
                os.remove(self.db_file)
            except OSError:
                pass

    async def _seed(self):
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        self.plan_id = f"plan-{uuid.uuid4()}"
        self.task_a = f"task-a-{uuid.uuid4()}"
        self.task_b = f"task-b-{uuid.uuid4()}"
        self.run_id = f"run-{uuid.uuid4()}"

        async with self.session_maker() as session:
            plan = Plan(id=self.plan_id, name="Test Plan", status="PLANNED", run_id=self.run_id, project_id="proj-1", version=1)
            task_a = Task(id=self.task_a, plan_id=self.plan_id, run_id=self.run_id, state="IN_PROGRESS", expected_artifacts=[], acceptance_criteria=[])
            task_b = Task(id=self.task_b, plan_id=self.plan_id, run_id=self.run_id, state="IN_PROGRESS", expected_artifacts=[], acceptance_criteria=[])
            session.add_all([plan, task_a, task_b])
            await session.commit()

    async def _run(self):
        await self._seed()
        async with self.session_maker() as session:
            common_path = "style.css"
            art_a = Artifact(task_id=self.task_a, path=common_path, storage_path="/tmp/a.css", hash="sha256:a", version=1)
            art_b = Artifact(task_id=self.task_b, path=common_path, storage_path="/tmp/b.css", hash="sha256:b", version=1)
            session.add_all([art_a, art_b])
            await session.commit()

            repo = MessageRepository(session)
            result = await repo.get_artifacts_for_plan(session, self.run_id, "proj-1", self.plan_id)
            self.assertEqual(len(result), 2)
            returned_task_ids = {art.task_id for art in result}
            self.assertEqual(returned_task_ids, {self.task_a, self.task_b})

    def test_get_artifacts_for_plan_dedup_is_task_scoped(self):
        asyncio.run(self._run())


if __name__ == "__main__":
    unittest.main()
