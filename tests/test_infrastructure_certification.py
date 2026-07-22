import unittest
import time
import threading
from engine.models import Message, MessageType, Plan, Task, PlanDraftSchema
from tests.test_harness import InfrastructureTestHarness
from engine.repository import MessageRepository

class TestInfrastructureCertification(unittest.TestCase):
    def setUp(self):
        self.harness = InfrastructureTestHarness()
        self.harness.setup()

    def tearDown(self):
        self.harness.teardown()

    def _create_plan(self, name="Test Plan"):
        draft = PlanDraftSchema(
            plan_name=name,
            tasks=[{
                "id": "T1",
                "description": "Test Task",
                "dependencies": [],
                "expected_artifacts": ["test.txt"],
                "acceptance_criteria": ["exists"]
            }]
        )
        return draft

    def test_01_golden_path(self):
        """
        Test: READY -> ASSIGNED -> CLAIMED -> SUBMITTED -> VERIFIED
        """
        print("\n[CERT] Running Golden Path...")
        self.harness.start(worker_mode="happy")

        draft = self._create_plan("Golden Path")
        plan_msg = Message(
            header={
                "sender": "Planner",
                "recipient": "Engine",
                "message_type": MessageType.PLAN_DRAFT_SUBMITTED
            },
            payload=draft.model_dump()
        )
        self.harness.messenger.send_to_engine(plan_msg)

        # Wait for plan
        time.sleep(1.0)
        repo = MessageRepository(self.harness.db_session)
        plan = repo.get_plan_by_name("Golden Path")
        self.assertIsNotNone(plan)
        task_id = plan.tasks[0].id

        # Sequence: READY -> ASSIGNED -> CLAIMED -> SUBMITTED
        self.harness.wait_for_task_state(task_id, "ASSIGNED", timeout=5.0)
        self.harness.wait_for_task_state(task_id, "CLAIMED", timeout=5.0)
        self.harness.wait_for_task_state(task_id, "SUBMITTED", timeout=5.0)
        
        print("[SUCCESS] Golden Path completed.")

    def test_02_double_ack_chaos(self):
        """
        Test: Worker sends two ACKs. Second one should be rejected.
        """
        print("\n[CERT] Running Double ACK Chaos...")
        self.harness.start(worker_mode="double_ack")

        draft = self._create_plan("Double ACK Plan")
        plan_msg = Message(
            header={
                "sender": "Planner",
                "recipient": "Engine",
                "message_type": MessageType.PLAN_DRAFT_SUBMITTED
            },
            payload=draft.model_dump()
        )
        self.harness.messenger.send_to_engine(plan_msg)

        time.sleep(1.0)
        repo = MessageRepository(self.harness.db_session)
        plan = repo.get_plan_by_name("Double ACK Plan")
        self.assertIsNotNone(plan)
        task_id = plan.tasks[0].id

        self.harness.wait_for_task_state(task_id, "CLAIMED", timeout=5.0)
        
        # Check if the second message was logged as REJECTED
        self.harness.assert_message_logged(MessageType.TASK_ACK, "REJECTED")
        print("[SUCCESS] Double ACK handled correctly.")

    def test_03_no_ack_chaos(self):
        """
        Test: Worker sends RESULT without ACK.
        Should be rejected by state consistency guard.
        """
        print("\n[CERT] Running No ACK Chaos...")
        self.harness.start(worker_mode="no_ack")

        draft = self._create_plan("No ACK Plan")
        plan_msg = Message(
            header={
                "sender": "Planner",
                "recipient": "Engine",
                "message_type": MessageType.PLAN_DRAFT_SUBMITTED
            },
            payload=draft.model_dump()
        )
        self.harness.messenger.send_to_engine(plan_msg)

        time.sleep(1.0)
        repo = MessageRepository(self.harness.db_session)
        plan = repo.get_plan_by_name("No ACK Plan")
        self.assertIsNotNone(plan)
        task_id = plan.tasks[0].id

        # Wait for assignment
        self.harness.wait_for_task_state(task_id, "ASSIGNED", timeout=5.0)
        
        # The worker sends RESULT immediately (no ACK).
        # We wait a bit to see if it mistakenly moves to SUBMITTED
        time.sleep(1.0)
        self.harness.assert_task_state(task_id, "ASSIGNED")
        self.harness.assert_message_logged(MessageType.TASK_RESULT, "REJECTED")
        print("[SUCCESS] No ACK chaos handled correctly.")

    def test_04_zombie_result_chaos(self):
        """
        Test: Late Result (Zombie).
        Scheduler timeouts ASSIGNED -> READY.
        Worker sends RESULT for the old assignment.
        Should be rejected.
        """
        print("\n[CERT] Running Zombie Result Chaos...")
        self.harness.start(worker_mode="late_result")

        draft = self._create_plan("Zombie Plan")
        plan_msg = Message(
            header={
                "sender": "Planner",
                "recipient": "Engine",
                "message_type": MessageType.PLAN_DRAFT_SUBMITTED
            },
            payload=draft.model_dump()
        )
        self.harness.messenger.send_to_engine(plan_msg)

        time.sleep(1.0)
        repo = MessageRepository(self.harness.db_session)
        plan = repo.get_plan_by_name("Zombie Plan")
        self.assertIsNotNone(plan)
        task_id = plan.tasks[0].id

        # 1. Wait for ASSIGNED
        self.harness.wait_for_task_state(task_id, "ASSIGNED", timeout=5.0)
        
        # 2. Wait for Scheduler to timeout the task (worker sleeps for 2s, scheduler interval 0.05s)
        print("Waiting for scheduler to timeout the task...")
        self.harness.wait_for_task_state(task_id, "READY", timeout=5.0)
        
        # 3. Now the worker will finally send its RESULT.
        # It's sending a result for a task that is now READY, not ASSIGNED.
        # This should be rejected by the state consistency guard.
        
        print("Waiting for late result to arrive...")
        time.sleep(2.5) 
        
        # 4. Check if task is still READY and result was rejected
        self.harness.assert_task_state(task_id, "READY")
        self.harness.assert_message_logged(MessageType.TASK_RESULT, "REJECTED")
        print("[SUCCESS] Zombie result (late result) correctly rejected.")

if __name__ == "__main__":
    unittest.main()
