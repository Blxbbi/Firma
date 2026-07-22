import os
import shutil
import tempfile
import uuid
import logging
import asyncio
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from engine.models import Base, Project, Plan, Task, Artifact
from engine.db import DatabaseManager
from engine.repository import MessageRepository

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("industrial-test")

async def run_isolation_test():
    # 1. Infrastructure Setup
    test_db = "test_industrial.db"
    if os.path.exists(test_db): os.remove(test_db)
    
    db_manager = DatabaseManager(db_url=f"sqlite:///{test_db}")
    db_manager.create_tables(Base)
    
    # Setup physical artifact store root
    tmp_dir = tempfile.TemporaryDirectory()
    artifact_root = Path(tmp_dir.name).resolve()
    
    # Repository initialized with the root for path validation
    repo = MessageRepository(artifact_store_root=str(artifact_root))

    try:
        # --- PHASE A: SETUP ---
        logger.info("--- Phase A: Setup ---")
        with db_manager.session_scope() as session:
            # Project A
            proj_a = Project(id="proj_a", name="Project A")
            session.add(proj_a)
            session.flush() # Ensure project is in DB for repo lookups
            plan_a1 = repo.create_plan_version(session, "proj_a", "Plan v1 A")
            repo.activate_plan(session, "proj_a", plan_a1.id)
            task_a1 = Task(id=str(uuid.uuid4()), plan_id=plan_a1.id, state="READY", 
                           expected_artifacts=["main.py"], acceptance_criteria=[])
            session.add(task_a1)
            
            # Project B
            proj_b = Project(id="proj_b", name="Project B")
            session.add(proj_b)
            session.flush() # Ensure project is in DB for repo lookups
            plan_b1 = repo.create_plan_version(session, "proj_b", "Plan v1 B")
            repo.activate_plan(session, "proj_b", plan_b1.id)
            task_b1 = Task(id=str(uuid.uuid4()), plan_id=plan_b1.id, state="READY", 
                           expected_artifacts=["main.py"], acceptance_criteria=[])
            session.add(task_b1)
            
            # Capture IDs for later
            a1_id = task_a1.id
            b1_id = task_b1.id
            a1_plan_id = plan_a1.id
            b1_plan_id = plan_b1.id
        
        logger.info("Projects A and B initialized with active plans and tasks.")

        # --- PHASE B: ABSOLUTE ISOLATION ---
        logger.info("\n--- Phase B: Absolute Isolation ---")
        with db_manager.session_scope() as session:
            # Save artifact for A
            path_a = artifact_root / "proj_a" / "v1" / "main.py"
            path_a.parent.mkdir(parents=True, exist_ok=True)
            path_a.write_text("Content A")
            
            res_a = repo.save_artifact(session, "proj_a", a1_id, "main.py", str(path_a), "hash_a")
            
            # Save artifact for B
            path_b = artifact_root / "proj_b" / "v1" / "main.py"
            path_b.parent.mkdir(parents=True, exist_ok=True)
            path_b.write_text("Content B")
            
            res_b = repo.save_artifact(session, "proj_b", b1_id, "main.py", str(path_b), "hash_b")
            
            assert res_a is True, "Failed to save artifact for Project A"
            assert res_b is True, "Failed to save artifact for Project B"
            logger.info("✅ Parallel Artifacts saved successfully.")

        # --- PHASE C: CROSS-PROJECT INJECTION ATTEMPT ---
        logger.info("\n--- Phase C: Cross-Project Injection Attempt ---")
        with db_manager.session_scope() as session:
            # Attempt to save Project B's task artifact into Project A's context
            # storage_path is for B, but we claim it's for Project A
            path_b = artifact_root / "proj_b" / "v1" / "main.py"
            res_injection = repo.save_artifact(session, "proj_a", b1_id, "main.py", str(path_b), "hash_b")
            
            assert res_injection is False, "CRITICAL FAILURE: Allowed cross-project artifact injection!"
            logger.info("✅ Cross-project injection rejected as expected.")

        # --- PHASE D: SUPERSEDE RACE ---
        logger.info("\n--- Phase D: Supersede Race ---")
        with db_manager.session_scope() as session:
            # 1. Claim task A1
            success_claim = repo.claim_task_atomic(session, "proj_a", a1_id, "worker_1")
            assert success_claim is True, "Failed to claim task A1"
            logger.info("Task A1 claimed by worker_1.")

        # 2. Activate new plan v2 for A (Supersedes v1)
        with db_manager.session_scope() as session:
            plan_a2 = repo.create_plan_version(session, "proj_a", "Plan v2 A")
            repo.activate_plan(session, "proj_a", plan_a2.id)
            logger.info("Plan v2 activated for Project A. Plan v1 should be superseded.")

        # 3. Try to update state of A1 (which belongs to v1)
        with db_manager.session_scope() as session:
            # This should FAIL because v1 is no longer active
            res_update = repo.update_task_state(session, "proj_a", a1_id, "SUBMITTED")
            assert res_update is False, "CRITICAL FAILURE: Allowed state update on superseded plan task!"
            logger.info("✅ State update on superseded task rejected.")

        # --- PHASE E: DOUBLE CLAIM ---
        logger.info("\n--- Phase E: Double Claim ---")
        # Reset B1 to READY
        with db_manager.session_scope() as session:
            task_b1 = session.query(Task).filter(Task.id == b1_id).first()
            task_b1.state = "READY"
        
        # Simulate two concurrent attempts using two separate scopes
        # (In a real multi-thread, these would be parallel, here we simulate the sequential race)
        with db_manager.session_scope() as session1:
            res1 = repo.claim_task_atomic(session1, "proj_b", b1_id, "worker_1")
        
        with db_manager.session_scope() as session2:
            res2 = repo.claim_task_atomic(session2, "proj_b", b1_id, "worker_2")
            
        assert res1 is True, "First claim should succeed"
        assert res2 is False, "Second claim must fail (CAS)"
        logger.info("✅ Double claim prevented. Only one worker won.")

        # --- PHASE F: VERSION LOCK ---
        logger.info("\n--- Phase F: Version Lock ---")
        # Manually set plan v1 of B to COMPLETED
        with db_manager.session_scope() as session:
            plan_b1_obj = session.query(Plan).filter(Plan.id == b1_plan_id).first()
            plan_b1_obj.status = "COMPLETED"
            # To make it realistic, we also remove active_plan_id
            project_b = session.query(Project).filter(Project.id == "proj_b").first()
            project_b.active_plan_id = None
        
        with db_manager.session_scope() as session:
            # Attempt to save artifact to a COMPLETED plan
            # We use a path that would normally be valid if it were active
            path_b = artifact_root / "proj_b" / "v1" / "extra.py"
            path_b.parent.mkdir(parents=True, exist_ok=True)
            path_b.write_text("locked content")
            
            res_lock = repo.save_artifact(session, "proj_b", b1_id, "extra.py", str(path_b), "hash_lock")
            assert res_lock is False, "CRITICAL FAILURE: Allowed artifact write to COMPLETED/Inactive plan!"
            logger.info("✅ Version lock enforced. No writes to inactive plans.")

        logger.info("\n" + "="*40)
        logger.info("INDUSTRIAL ISOLATION TEST: PASSED")
        logger.info("="*40)

    finally:
        tmp_dir.cleanup()
        if os.path.exists(test_db): os.remove(test_db)

if __name__ == "__main__":
    asyncio.run(run_isolation_test())
