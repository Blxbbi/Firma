import logging
import uuid
import random
import string
import sys
import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

# Add root directory to sys.path to allow imports from 'engine'
sys.path.append(str(Path(__file__).parent.parent.parent))

from engine.services.guardian import GuardianPipeline
from engine.services.artifact_store import ArtifactStore
from engine.models import WorkerResponse, Task, Plan, ExecutionPhase, AssignedRole, TaskEvent, FileAction, SubmissionOutcome
from sqlalchemy.orm import Session
from unittest.mock import MagicMock

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] STRESS-HARNESS: %(message)s')
logger = logging.getLogger("StressHarness")

@dataclass
class AttackResult:
    scenario: str
    payload: Dict[str, Any]
    success: bool # True if the kernel correctly rejected the attack
    message: str
    invariant_violated: bool = False

class PayloadGenerator:
    """Generates malicious or extreme payloads to test Kernel robustness."""
    
    @staticmethod
    def random_string(length: int) -> str:
        return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

    def generate_schema_attack(self) -> Tuple[str, Dict[str, Any]]:
        """Generates a payload that violates the Artifact Contract."""
        scenarios = [
            ("EMPTY_FILES", {"artifacts": {"files": []}}),
            ("MISSING_PATH", {"artifacts": {"files": [{"content": "foo", "action": "CREATE"}]}}),
            ("MISSING_ACTION", {"artifacts": {"files": [{"path": "f.py", "content": "foo"}]}}),
            ("MISSING_CONTENT_CREATE", {"artifacts": {"files": [{"path": "f.py", "action": "CREATE"}]}}),
            ("INVALID_ACTION", {"artifacts": {"files": [{"path": "f.py", "action": "SQUASH", "content": "foo"}]}}),
            ("ABSOLUTE_PATH", {"artifacts": {"files": [{"path": "/etc/passwd", "action": "CREATE", "content": "foo"}]}}),
            ("PATH_TRAVERSAL", {"artifacts": {"files": [{"path": "../secret.txt", "action": "CREATE", "content": "foo"}]}}),
            ("NESTED_TRAVERSAL", {"artifacts": {"files": [{"path": "a/../../b", "action": "CREATE", "content": "foo"}]}}),
            ("LONG_PATH", {"artifacts": {"files": [{"path": "a" * 5000, "action": "CREATE", "content": "foo"}]}}),
            ("DELETE_WITH_CONTENT", {"artifacts": {"files": [{"path": "f.py", "action": "DELETE", "content": "should be empty"}]}}),
            ("NOT_A_DICT", {"artifacts": "not a dict"}),
            ("NOT_A_LIST", {"artifacts": {"files": "not a list"}})
        ]
        name, artifacts = random.choice(scenarios)
        
        payload = {
            "protocol_version": "1.0",
            "message_id": str(uuid.uuid4()),
            "task_id": "T1",
            "state_revision": 1,
            "event": "CODE_SUBMITTED",
            "sender_role": "CODER",
            "artifacts": artifacts,
            "timestamp": datetime.utcnow().isoformat(),
            "logs": "Attacking!"
        }
        return name, payload

    def generate_payload_extreme(self) -> Tuple[str, Dict[str, Any]]:
        """Generates extreme payloads to test stability (memory/performance)."""
        scenarios = [
            ("HUGE_CONTENT", {"artifacts": {"files": [{"path": "big.txt", "action": "CREATE", "content": "X" * (10 * 1024 * 1024)}]}}), # 10MB
            ("MANY_FILES", {"artifacts": {"files": [{"path": f"file_{i}.py", "action": "CREATE", "content": "print(1)"} for i in range(1000)]}}),
            ("UNICODE_EDGE", {"artifacts": {"files": [{"path": "🔥.py", "action": "CREATE", "content": "print('你好')"}]}}),
        ]
        name, artifacts = random.choice(scenarios)
        
        payload = {
            "protocol_version": "1.0",
            "message_id": str(uuid.uuid4()),
            "task_id": "T1",
            "state_revision": 1,
            "event": "CODE_SUBMITTED",
            "sender_role": "CODER",
            "artifacts": artifacts,
            "timestamp": datetime.utcnow().isoformat(),
            "logs": "Stress testing!"
        }
        return name, payload

class StressHarness:
    """
    The Adversarial Stress Harness.
    Orchestrates attacks against the GuardianPipeline and verifies invariants.
    """
    def __init__(self, guardian: GuardianPipeline, artifact_store: ArtifactStore):
        self.guardian = guardian
        self.artifact_store = artifact_store
        self.generator = PayloadGenerator()
        self.results: List[AttackResult] = []

    def setup_mock_environment(self, session: Session):
        """Sets up a clean mock task and plan for the attack."""
        plan = MagicMock()
        plan.project_id = "stress-proj"
        plan.version = 1
        
        task = MagicMock()
        task.id = "T1"
        task.plan = plan
        task.execution_phase = ExecutionPhase.CODING.value
        task.assigned_role = AssignedRole.CODER.value
        task.state_revision = 1
        task.attempt_count = 0
        task.updated_at = datetime.utcnow()
        
        session.query.return_value.filter.return_value.first.return_value = task
        return task

    def run_schema_fuzzing(self, session: Session, iterations: int = 100):
        logger.info(f"Starting Schema Fuzzing: {iterations} iterations")
        
        for i in range(iterations):
            task = self.setup_mock_environment(session)
            name, payload = self.generator.generate_schema_attack()
            
            # Invariant: No invalid submission should ever be persisted
            # We mock repository to avoid actual DB writes during fuzzing, but check if store was called
            with patch('engine.repository.MessageRepository.is_message_processed', return_value=False), \
                 patch('engine.repository.MessageRepository.transition_task_atomic', return_value=True), \
                 patch('engine.repository.MessageRepository.mark_message_processed', return_value=True):
                
                self.artifact_store.persist_artifacts.reset_mock()
                success, message = self.guardian.process_response(session, payload)
                
                # Invariant Check:
                # 1. Should not have been "SUCCESS"
                # 2. ArtifactStore must NOT have been called
                # 3. Message should contain "SCHEMA_INVALID"
                
                violated = False
                if message == "SUCCESS":
                    violated = True
                if self.artifact_store.persist_artifacts.called:
                    violated = True
                if "SCHEMA_INVALID" not in message:
                    violated = True
                
                self.results.append(AttackResult(
                    scenario=name,
                    payload=payload,
                    success=not violated,
                    message=message,
                    invariant_violated=violated
                ))
        
        logger.info("Schema Fuzzing completed.")

    def run_payload_stress(self, session: Session, iterations: int = 50):
        logger.info(f"Starting Payload Stress Testing: {iterations} iterations")
        
        for i in range(iterations):
            task = self.setup_mock_environment(session)
            name, payload = self.generator.generate_payload_extreme()
            
            with patch('engine.repository.MessageRepository.is_message_processed', return_value=False), \
                 patch('engine.repository.MessageRepository.transition_task_atomic', return_value=True), \
                 patch('engine.repository.MessageRepository.mark_message_processed', return_value=True):
                
                try:
                    success, message = self.guardian.process_response(session, payload)
                    # Extreme payloads should either be SUCCESS (if valid) or SCHEMA_INVALID
                    # They should NEVER crash the kernel
                    violated = False
                    if "Internal Guardian Error" in message:
                        violated = True
                    
                    self.results.append(AttackResult(
                        scenario=name,
                        payload=payload,
                        success=not violated,
                        message=message,
                        invariant_violated=violated
                    ))
                except Exception as e:
                    self.results.append(AttackResult(
                        scenario=name,
                        payload=payload,
                        success=False,
                        message=str(e),
                        invariant_violated=True
                    ))
        
        logger.info("Payload Stress Testing completed.")

    def generate_report(self):
        total = len(self.results)
        violations = [r for r in self.results if r.invariant_violated]
        
        print("\n" + "="*50)
        print("FIRMA ADVERSARIAL STRESS REPORT")
        print("="*50)
        print(f"Total Attacks:      {total}")
        print(f"Invariants Violated: {len(violations)}")
        print(f"Success Rate:       {(1 - len(violations)/total)*100:.2f}%")
        print("-" * 50)
        
        if violations:
            print("VIOLATIONS FOUND:")
            for v in violations:
                print(f"Scenario: {v.scenario} | Error: {v.message}")
        else:
            print("NO INVARIANTS VIOLATED. KERNEL IS ROBUST.")
        print("="*50 + "\n")

# --- Mock objects for standalone run ---
from unittest.mock import MagicMock

if __name__ == "__main__":
    # Setup
    mock_session = MagicMock(spec=Session)
    mock_store = MagicMock(spec=ArtifactStore)
    guardian = GuardianPipeline(mock_store)
    
    harness = StressHarness(guardian, mock_store)
    
    # Execute
    harness.run_schema_fuzzing(mock_session, iterations=100)
    harness.run_payload_stress(mock_session, iterations=50)
    
    # Report
    harness.generate_report()
