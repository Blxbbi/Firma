import os
import hashlib
import shutil
import logging
import asyncio
import aiofiles
import time
from pathlib import Path
from typing import List, Dict, Any, NamedTuple, Optional
from sqlalchemy import select
from engine.models import ArtifactChange, FileAction
from engine.settings import ARTIFACT_DIR

try:
    from engine.services.telemetry import telemetry
except ImportError:
    telemetry = None


logger = logging.getLogger(__name__)

class StoredArtifact(NamedTuple):
    path: str
    storage_path: str
    hash: str

class ArtifactStore:
    """
    Handles the physical persistence of artifacts to the filesystem.
    Fully Asynchronous implementation.
    """

    def __init__(self, base_dir: Optional[str] = None):
        if base_dir:
            self.base_dir = Path(base_dir)
        else:
            self.base_dir = ARTIFACT_DIR
        
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def _compute_hash(self, file_path: Path) -> str:
        """Computes the SHA256 hash of a file's content asynchronously."""
        sha256_hash = hashlib.sha256()
        async with aiofiles.open(file_path, "rb") as f:
            while True:
                chunk = await f.read(4096)
                if not chunk:
                    break
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()

    async def persist_artifacts(self, session, project_id: str, version: int, task_id: str, artifacts: List[ArtifactChange], run_id: Optional[str] = None) -> bool:
        """
        Persists a set of artifacts to the filesystem using the project hierarchy.
        Returns True if all artifacts were successfully written.
        """
        t0 = time.perf_counter_ns()
        if not artifacts:
            logger.warning(f"No artifacts provided for task {task_id} in {project_id}. Rejecting submission.")
            return False
        
        try:
            # Industrial Path: data/artifacts/{run_id}/{task_id}/
            task_dir = self.base_dir / (run_id or "unknown_run") / task_id
            
            # Use asyncio.to_thread for blocking filesystem operations
            await asyncio.to_thread(task_dir.mkdir, parents=True, exist_ok=True)
            
            stored_results = []
            total_bytes = 0

            for art in artifacts:
                path = art.path if hasattr(art, 'path') else art.get('path')
                action = art.action if hasattr(art, 'action') else art.get('action')
                content = art.content if hasattr(art, 'content') else art.get('content')
                
                # Normalize path to prevent traversal attacks
                clean_path = Path(path).relative_to("/") if Path(path).is_absolute() else Path(path)
                target_path = task_dir / clean_path
                await asyncio.to_thread(target_path.parent.mkdir, parents=True, exist_ok=True)

                if action in {FileAction.CREATE, FileAction.UPDATE}:
                    if content is None:
                        raise ValueError(f"Content required for action {action} at {path}")
                    
                    async with aiofiles.open(target_path, mode='w', encoding='utf-8') as f:
                        await f.write(content)
                        
                    file_hash = await self._compute_hash(target_path)
                    total_bytes += len(content)
                    
                    stored_results.append(StoredArtifact(
                        path=path,
                        storage_path=str(target_path),
                        hash=file_hash
                    ))

                elif action == FileAction.DELETE:
                    if await asyncio.to_thread(target_path.exists):
                        await asyncio.to_thread(target_path.unlink)
                    stored_results.append(StoredArtifact(
                        path=path,
                        storage_path=str(target_path),
                        hash="DELETED"
                    ))
                else:
                    raise ValueError(f"Invalid action '{action}' for artifact {path}.")

            # Save metadata to DB via the session (ASYNCHRONOUS)
            from engine.repository import MessageRepository
            repo = MessageRepository(artifact_store_root=str(self.base_dir))
            for result in stored_results:
                logger.info(f"Persisting artifact metadata to DB: task={task_id}, path={result.path}")
                if not await repo.save_artifact(
                    session=session, 
                    project_id=project_id, 
                    task_id=task_id, 
                    path=result.path, 
                    storage_path=result.storage_path, 
                    file_hash=result.hash,
                    run_id=run_id
                ):
                    raise RuntimeError(f"Failed to save artifact metadata for {result.path}")
            
            # FORCE FLUSH via async session
            await session.flush()
            logger.info(f"Successfully flushed {len(stored_results)} artifacts for task {task_id}")

            if telemetry:
                telemetry.observe("artifact_write_latency_ns", time.perf_counter_ns() - t0)
                telemetry.increment_by("artifact_bytes_written_total", total_bytes)

            return True

        except Exception as e:
            if telemetry:
                telemetry.observe("artifact_write_latency_ns", time.perf_counter_ns() - t0)
            logger.exception(f"CRITICAL: Artifact persistence exception for task {task_id} in {project_id}: {str(e)}")
            await self._rollback(task_dir)
            return False

    async def _rollback(self, task_dir: Path):
        """Removes all files in the task directory if a batch write fails."""
        try:
            if await asyncio.to_thread(task_dir.exists):
                await asyncio.to_thread(shutil.rmtree, task_dir)
        except Exception as e:
            logger.error(f"Rollback failed for {task_dir}: {str(e)}")

    async def get_artifacts(self, session, run_id: str, project_id: str, version: int, task_id: str) -> List[Dict[str, str]]:
        """
        Retrieves all current artifacts for a task.
        Returns a list of {'path': ..., 'content': ...}
        """
        t0 = time.perf_counter_ns()
        from engine.repository import MessageRepository
        from engine.models import Plan
        repo = MessageRepository(artifact_store_root=str(self.base_dir))
        
        logger.info(f"Fetching artifacts for Run: {run_id}, Project: {project_id}, Version: {version}, Task: {task_id}")
        
        # 1. Find the plan ID for this project and version (ASYNCHRONOUS)
        result = await session.execute(
            select(Plan).filter(Plan.project_id == project_id, Plan.version == version, Plan.run_id == run_id)
        )
        plan = result.scalars().first()
        
        if not plan:
            logger.warning(f"No plan found for project {project_id} version {version} in run {run_id}")
            if telemetry:
                telemetry.observe("artifact_read_latency_ns", time.perf_counter_ns() - t0)
            return []
        
        # 2. Get all artifacts for that plan (ASYNCHRONOUS)
        artifacts_meta = await repo.get_artifacts_for_plan(session, run_id, project_id, plan.id)
        
        # 3. Filter for the specific task and load content
        task_artifacts = []
        for art in artifacts_meta:
            if art.task_id == task_id:
                try:
                    async with aiofiles.open(art.storage_path, mode='r', encoding='utf-8') as f:
                        content = await f.read()
                    task_artifacts.append({"path": art.path, "content": content})
                except Exception as e:
                    logger.error(f"Failed to read artifact {art.path} from {art.storage_path}: {e}")
        
        if telemetry:
            telemetry.observe("artifact_read_latency_ns", time.perf_counter_ns() - t0)
        return task_artifacts
