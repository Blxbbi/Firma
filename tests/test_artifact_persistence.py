import unittest
import os
import shutil
import tempfile
import hashlib
import uuid
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from engine.models import Base, Plan, Task, Message, MessageHeader, MessageType, ArtifactChange, FileAction
from engine.repository import MessageRepository
from engine.workflow import process_task_message
from engine.services.artifact_store import ArtifactStore
from unittest.mock import patch

class TestArtifactPersistence(unittest.TestCase):
    def setUp(self):
        # 1. DB Setup: Unique File SQLite to avoid memory/locking issues
        self.db_file = f"test_persistence_{uuid.uuid4()}.db"
        self.engine = create_engine(f"sqlite:///{self.db_file}")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.session = self.Session()
        self.repo = MessageRepository(self.session)

        # 2. Filesystem Setup: Temporary Directory
        self.test_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.test_dir.name)

        # 3. Setup a basic plan and task in DB
        self.plan_id = "test-plan-123"
        self.task_id = "T1"
        
        plan = Plan(id=self.plan_id, name="Test Plan", status="PLANNED")
        self.session.add(plan)
        
        task = Task(
            id=self.task_id, 
            plan_id=self.plan_id, 
            state="IN_PROGRESS", 
            expected_artifacts=[], 
            acceptance_criteria=[]
        )
        self.session.add(task)
        self.session.commit()

    def tearDown(self):
        self.session.close()
        if hasattr(self, 'db_file') and os.path.exists(self.db_file):
            try:
                os.remove(self.db_file)
            except OSError:
                pass
        self.test_dir.cleanup()

    def _create_task_result_message(self, artifacts_data: list):
        """Helper to create a TASK_RESULT message."""
        header = MessageHeader(
            sender="worker-1",
            recipient="engine",
            message_type=MessageType.TASK_RESULT,
            plan_id=self.plan_id
        )
        return Message(
            header=header,
            payload={"artifacts": artifacts_data}
        )

    def _compute_real_sha256(self, path: Path) -> str:
        """Ground truth hash computation."""
        sha256_hash = hashlib.sha256()
        with open(path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def test_artifact_written_and_hash_correct(self):
        """Test 1: Artifact is written and hash in DB matches real file."""
        content = "Hello World\nDeterministic AI"
        artifacts_data = [{"path": "main.py", "content": content, "action": "CREATE"}]
        message = self._create_task_result_message(artifacts_data)

        with patch.dict(os.environ, {"FIRMA_ARTIFACT_STORE_DIR": str(self.base_path)}):
            res = process_task_message(self.session, message, self.task_id, MessageType.TASK_RESULT)
            self.assertTrue(res.passed)
            self.assertEqual(self.repo.get_task(self.task_id).state, "SUBMITTED")

        file_path = self.base_path / self.plan_id / self.task_id / "main.py"
        self.assertTrue(file_path.exists())
        self.assertEqual(file_path.read_text(encoding="utf-8"), content)

        from engine.models import Artifact
        db_art = self.session.query(Artifact).filter_by(task_id=self.task_id, path="main.py").first()
        self.assertIsNotNone(db_art)
        self.assertEqual(db_art.hash, self._compute_real_sha256(file_path))

    def test_write_failure_prevents_submission(self):
        """Test 2: Write failure prevents SUBMITTED status."""
        artifacts_data = [{"path": "main.py", "content": None, "action": "CREATE"}]
        message = self._create_task_result_message(artifacts_data)

        with patch.dict(os.environ, {"FIRMA_ARTIFACT_STORE_DIR": str(self.base_path)}):
            res = process_task_message(self.session, message, self.task_id, MessageType.TASK_RESULT)
            self.assertFalse(res.passed)
            self.assertIn(res.error_code, ["ERR_ARTIFACT_SCHEMA", "ERR_PERSISTENCE_FAILED"])
            self.assertNotEqual(self.repo.get_task(self.task_id).state, "SUBMITTED")

    def test_batch_write_rollback(self):
        """Test 3: Batch write failure triggers complete rollback."""
        artifacts_data = [
            {"path": "file1.py", "content": "content1", "action": "CREATE"},
            {"path": "file2.py", "content": None, "action": "CREATE"} 
        ]
        message = self._create_task_result_message(artifacts_data)

        with patch.dict(os.environ, {"FIRMA_ARTIFACT_STORE_DIR": str(self.base_path)}):
            res = process_task_message(self.session, message, self.task_id, MessageType.TASK_RESULT)
            self.assertFalse(res.passed)
            from engine.models import Artifact
            arts = self.session.query(Artifact).filter_by(task_id=self.task_id).all()
            self.assertEqual(len(arts), 0)
            task_dir = self.base_path / self.plan_id / self.task_id
            self.assertFalse(task_dir.exists(), "Task directory should have been rolled back")
            self.assertNotEqual(self.repo.get_task(self.task_id).state, "SUBMITTED")

    def test_duplicate_task_result_handling(self):
        """Test 4: Duplicate TASK_RESULT handling is idempotent/versioned."""
        content_v1 = "Content V1"
        content_v2 = "Content V2"
        
        msg1 = self._create_task_result_message([{"path": "main.py", "content": content_v1, "action": "CREATE"}])
        with patch.dict(os.environ, {"FIRMA_ARTIFACT_STORE_DIR": str(self.base_path)}):
            process_task_message(self.session, msg1, self.task_id, MessageType.TASK_RESULT)
        
        self.session.commit()
        from engine.models import Artifact
        art_v1 = self.session.query(Artifact).filter_by(task_id=self.task_id, path="main.py").first()
        version_v1 = art_v1.version

        msg2 = self._create_task_result_message([{"path": "main.py", "content": content_v2, "action": "UPDATE"}])
        with patch.dict(os.environ, {"FIRMA_ARTIFACT_STORE_DIR": str(self.base_path)}):
            process_task_message(self.session, msg2, self.task_id, MessageType.TASK_RESULT)
        
        self.session.commit()
        self.session.expire_all()
        art_v2 = self.session.query(Artifact).filter_by(task_id=self.task_id, path="main.py").first()
        
        self.assertEqual(art_v2.version, version_v1 + 1)
        file_path = self.base_path / self.plan_id / self.task_id / "main.py"
        self.assertEqual(file_path.read_text(encoding="utf-8"), content_v2)

    def test_unicode_file_handling(self):
        """Test 5: Unicode characters are handled correctly and hash is stable."""
        unicode_content = "π = 3.14159\n🚀 Launch\nこんにちは\nSpecial: © ® ™"
        artifacts_data = [{"path": "unicode.txt", "content": unicode_content, "action": "CREATE"}]
        message = self._create_task_result_message(artifacts_data)

        with patch.dict(os.environ, {"FIRMA_ARTIFACT_STORE_DIR": str(self.base_path)}):
            res = process_task_message(self.session, message, self.task_id, MessageType.TASK_RESULT)
            self.assertTrue(res.passed)

        file_path = self.base_path / self.plan_id / self.task_id / "unicode.txt"
        self.assertTrue(file_path.exists())
        self.assertEqual(file_path.read_text(encoding="utf-8"), unicode_content)
        
        from engine.models import Artifact
        db_art = self.session.query(Artifact).filter_by(task_id=self.task_id, path="unicode.txt").first()
        self.assertEqual(db_art.hash, self._compute_real_sha256(file_path))

if __name__ == "__main__":
    unittest.main()
