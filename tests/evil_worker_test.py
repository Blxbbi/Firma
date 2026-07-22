import logging
import json
import uuid
import time
import threading
import random
import hashlib
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Tuple, Optional

from sqlalchemy.orm import Session
from engine.db import DatabaseManager
from engine.models import Base, Project, Plan, Task, ExecutionPhase, AssignedRole, TaskEvent, Message, MessageHeader, MessageType, TaskTransitionLog, TaskEventLog, ProcessedEvent
from engine.workflow import process_task_message

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("brutal-simulator")

class StressReport:
    """Collects results of stress tests for the final matrix."""
    def __init__(self):
        self.results = []

    def add_result(self, scenario: str, attempts: int, accepted: int, rejected: int, expected: str, status: str):
        self.results.append({
            "scenario": scenario,
            "attempts": attempts,
            "accepted": accepted,
            "rejected": rejected,
            "expected": expected,
            "status": status
        })

    def print_matrix(self):
        print("\n" + "="*100)
        print(f"{'Szenario':<30} | {'Versuche':<10} | {'Acc':<5} | {'Rej':<5} | {'Erwartung':<20} | {'Status':<10}")
        print("-" * 100)
        for r in self.results:
            print(f"{r['scenario']:<30} | {r['attempts']:<10} | {r['accepted']:<5} | {r['rejected']:<5} | {r['expected']:<20} | {r['status']:<10}")
        print("="*100 + "\n")

class BrutalSimulator:
    def __init__(self, db_url: str = "sqlite:///brutal_test.db"):
        self.db_manager = DatabaseManager(db_url=db_url)
        self.report = StressReport()
        
        with self.db_manager.session_scope() as session:
            Base.metadata.drop_all(session.bind)
            Base.metadata.create_all(session.bind)

    def setup_baseline_task(self, project_id="proj_stress", task_id="T_STRESS") -> Tuple[str, str, str]:
        """Creates a fresh project, plan and task for a scenario."""
        with self.db_manager.session_scope() as session:
            # NUCLEAR OPTION: Reset the entire schema to guarantee no leftover state
            Base.metadata.drop_all(session.bind)
            Base.metadata.create_all(session.bind)
            
            proj = Project(id=project_id, name="Stress Project")
            session.add(proj)
            session.commit()
            
            plan = Plan(id="plan_stress", project_id=project_id, name="Stress Plan", version=1)
            session.add(plan)
            session.commit()
            
            proj.active_plan_id = plan.id
            session.commit()
            
            task = Task(
                id=task_id, 
                plan_id=plan.id, 
                state="READY", 
                execution_phase="CODING", 
                assigned_role="CODER", 
                state_revision=0,
                expected_artifacts=[],
                acceptance_criteria=[]
            )
            session.add(task)
            session.commit()
            
        return project_id, "plan_stress", task_id

    def get_task_hash(self, session: Session, task_id: str) -> str:
        """Computes a deterministic hash of the task state, ignoring non-deterministic fields."""
        task = session.query(Task).filter(Task.id == task_id).first()
        if not task:
            return "NOT_FOUND"
            
        from engine.models import TaskTransitionLog
        # Get transition logs ordered by revision for determinism
        logs = session.query(TaskTransitionLog).filter(
            TaskTransitionLog.task_id == task_id
        ).order_by(TaskTransitionLog.previous_revision.asc()).all()
        
        # Normalize the state
        state_dict = {
            "execution_phase": task.execution_phase,
            "assigned_role": task.assigned_role,
            "state_revision": task.state_revision,
            "transitions": [
                {
                    "from": l.from_phase,
                    "event": l.event,
                    "to": l.to_phase,
                    "rev": l.previous_revision
                }
                for l in logs
            ]
        }
        
        dump = json.dumps(state_dict, sort_keys=True)
        return hashlib.sha256(dump.encode()).hexdigest()

    def create_worker_msg(self, task_id: str, revision: int, event: TaskEvent, msg_id=None) -> Message:
        payload = {
            "protocol_version": "1.0",
            "message_id": msg_id or str(uuid.uuid4()),
            "task_id": task_id,
            "state_revision": revision,
            "event": event.value,
            "timestamp": datetime.utcnow().isoformat()
        }
        return Message(
            header=MessageHeader(
                message_id=payload["message_id"],
                sender="StressWorker",
                recipient="Engine",
                message_type=MessageType.TASK_RESULT
            ),
            payload=payload
        )

    def run_concurrency_test(self):
        """SCENARIO 1: True Concurrency Race."""
        print("\n--- Scenario 1: Concurrency Race ---")
        proj_id, _, task_id = self.setup_baseline_task()
        num_workers = 5
        barrier = threading.Barrier(num_workers)
        results = []

        def attempt_transition():
            barrier.wait() # Sync start
            with self.db_manager.session_scope() as session:
                msg = self.create_worker_msg(task_id, revision=0, event=TaskEvent.CODE_SUBMITTED)
                success = process_task_message(session, msg, task_id, MessageType.TASK_RESULT, proj_id)
                return success

        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(attempt_transition) for _ in range(num_workers)]
            for f in as_completed(futures):
                results.append(f.result())

        acc = sum(results)
        rej = num_workers - acc
        status = "PASS" if acc == 1 and rej == 4 else "FAIL"
        self.report.add_result("Concurrency Race", num_workers, acc, rej, "1 Acc / 4 Rej", status)
        print(f"Result: {status} ({acc} Acc, {rej} Rej)")

    def run_storm_test(self):
        """SCENARIO 2: Duplicate Replay Storm."""
        print("\n--- Scenario 2: Duplicate Replay Storm ---")
        proj_id, _, task_id = self.setup_baseline_task()
        num_msgs = 100
        msg_id = str(uuid.uuid4())
        
        success_count = 0
        idempotent_count = 0
        error_count = 0

        def attempt_duplicate():
            with self.db_manager.session_scope() as session:
                msg = self.create_worker_msg(task_id, revision=0, event=TaskEvent.CODE_SUBMITTED, msg_id=msg_id)
                # We need to know IF it was a new success or just idempotent
                from engine.workflow import process_task_message_detailed
                res, reason = process_task_message_detailed(session, msg, task_id, MessageType.TASK_RESULT, proj_id)
                return res, reason

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(attempt_duplicate) for _ in range(num_msgs)]
            for f in as_completed(futures):
                res, reason = f.result()
                if res:
                    if reason == "SUCCESS": success_count += 1
                    elif reason == "ALREADY_PROCESSED": idempotent_count += 1
                else:
                    error_count += 1

        status = "PASS" if success_count == 1 and idempotent_count == 99 else "FAIL"
        self.report.add_result("Storm (Duplicates)", num_msgs, success_count, error_count, "1 Acc / 99 Idem", status)
        print(f"Result: {status} ({success_count} New, {idempotent_count} Idempotent, {error_count} Rej)")

    def run_zombie_flood(self):
        """SCENARIO 4: Terminal Zombie Flood."""
        print("\n--- Scenario 4: Terminal Zombie Flood ---")
        proj_id, _, task_id = self.setup_baseline_task()
        
        # Force task to Terminal State
        with self.db_manager.session_scope() as session:
            task = session.query(Task).filter(Task.id == task_id).first()
            task.state = "VERIFIED"
            task.execution_phase = "COMPLETE"
            session.commit()

        num_msgs = 50
        results = []

        def attempt_zombie():
            with self.db_manager.session_scope() as session:
                msg = self.create_worker_msg(task_id, revision=0, event=TaskEvent.CODE_SUBMITTED)
                return process_task_message(session, msg, task_id, MessageType.TASK_RESULT, proj_id)

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(attempt_zombie) for _ in range(num_msgs)]
            for f in as_completed(futures):
                results.append(f.result())

        acc = sum(results)
        rej = num_msgs - acc
        status = "PASS" if acc == 0 and rej == 50 else "FAIL"
        self.report.add_result("Zombie Flood", num_msgs, acc, rej, "0 Acc / 50 Rej", status)
        print(f"Result: {status} ({acc} Acc, {rej} Rej)")

    def run_shuffle_test(self):
        """SCENARIO 5: Event-Ordering Shuffle."""
        print("\n--- Scenario 5: Event-Ordering Shuffle ---")
        proj_id, _, task_id = self.setup_baseline_task()
        
        # sequence: (revision, event)
        events = [
            (0, TaskEvent.CODE_SUBMITTED),
            (1, TaskEvent.VERIFY_SUCCESS),
            (0, TaskEvent.CODE_SUBMITTED), # duplicate/stale
            (2, TaskEvent.VERIFY_SUCCESS), # future/wrong
        ]
        random.shuffle(events)
        
        results = []
        for rev, ev in events:
            with self.db_manager.session_scope() as session:
                msg = self.create_worker_msg(task_id, revision=rev, event=ev)
                results.append(process_task_message(session, msg, task_id, MessageType.TASK_RESULT, proj_id))
        
        acc = sum(results)
        # We expect exactly 2 transitions if ordered correctly, 
        # but if shuffled, maybe only the first valid one sticks.
        # The key is that it doesn't crash and remains consistent.
        status = "PASS" if acc <= 2 else "FAIL" 
        self.report.add_result("Ordering Shuffle", len(events), acc, len(events)-acc, "Max 2 Acc", status)
        print(f"Result: {status} ({acc} Acc)")

    def run_fuzz_test(self):
        """SCENARIO 6: Fuzz Testing."""
        print("\n--- Scenario 6: Fuzz Testing ---")
        proj_id, _, task_id = self.setup_baseline_task()
        num_msgs = 100
        crashes = 0
        
        all_events = list(TaskEvent)
        
        for _ in range(num_msgs):
            try:
                with self.db_manager.session_scope() as session:
                    msg = self.create_worker_msg(
                        task_id, 
                        revision=random.randint(0, 100), 
                        event=random.choice(all_events)
                    )
                    process_task_message(session, msg, task_id, MessageType.TASK_RESULT, proj_id)
            except Exception as e:
                logger.error(f"Fuzz Crash: {e}")
                crashes += 1
        
        status = "PASS" if crashes == 0 else "FAIL"
        self.report.add_result("Fuzzing", num_msgs, 0, 0, "0 Crashes", status)
        print(f"Result: {status} ({crashes} crashes)")

    def run_deterministic_replay(self):
        """SCENARIO 7: Deterministic Parallel Replay."""
        print("\n--- Scenario 7: Deterministic Parallel Replay ---")
        
        def execute_sequence(proj_id, task_id, sequence):
            """Executes a sequence and returns the final task hash and log."""
            # sequence: [(rev, event, msg_id)]
            accepted_ids = []
            for rev, ev, mid in sequence:
                with self.db_manager.session_scope() as session:
                    msg = self.create_worker_msg(task_id, revision=rev, event=ev, msg_id=mid)
                    from engine.workflow import process_task_message_detailed
                    res, reason = process_task_message_detailed(session, msg, task_id, MessageType.TASK_RESULT, proj_id)
                    print(f"[Replay] Msg {mid} -> {res}, {reason}")
                    if res:
                        accepted_ids.append(mid)
                
                with self.db_manager.session_scope() as session:
                    h = self.get_task_hash(session, task_id)
                    # Get logs
                    from engine.models import TaskTransitionLog
                    logs = session.query(TaskTransitionLog).filter(TaskTransitionLog.task_id == task_id).order_by(TaskTransitionLog.previous_revision.asc()).all()
                    log_summary = [f"{l.from_phase}->{l.to_phase}" for l in logs]
                    
                return h, log_summary, accepted_ids

        # 1. Setup and Parallel Run
        proj_id, _, task_id = self.setup_baseline_task()
        sequence = [
            (0, TaskEvent.CODE_SUBMITTED, str(uuid.uuid4())),
            (1, TaskEvent.VERIFY_SUCCESS, str(uuid.uuid4())),
            (0, TaskEvent.CODE_SUBMITTED, str(uuid.uuid4())), # stale
            (1, TaskEvent.VERIFY_SUCCESS, str(uuid.uuid4())), # stale
        ]
        
        # We'll run it in parallel first
        num_workers = len(sequence)
        barrier = threading.Barrier(num_workers)
        parallel_accepted = []
        
        def parallel_worker(rev, ev, mid):
            barrier.wait()
            with self.db_manager.session_scope() as session:
                msg = self.create_worker_msg(task_id, revision=rev, event=ev, msg_id=mid)
                if process_task_message(session, msg, task_id, MessageType.TASK_RESULT, proj_id):
                    return mid
                return None

        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(parallel_worker, *s) for s in sequence]
            for f in as_completed(futures):
                res = f.result()
                if res: parallel_accepted.append(res)

        with self.db_manager.session_scope() as session:
            hash_parallel = self.get_task_hash(session, task_id)
            from engine.models import TaskTransitionLog
            logs_parallel = [f"{l.from_phase}->{l.to_phase}" for l in session.query(TaskTransitionLog).filter(TaskTransitionLog.task_id == task_id).order_by(TaskTransitionLog.previous_revision.asc()).all()]

        # 2. Reset and Sequential Replay of exactly the accepted events
        proj_id_2, _, task_id_2 = self.setup_baseline_task()
        # Map original sequence to accepted IDs
        accepted_sequence = [s for s in sequence if s[2] in parallel_accepted]
        
        hash_seq, logs_seq, _ = execute_sequence(proj_id_2, task_id_2, accepted_sequence)
        
        status = "PASS" if hash_parallel == hash_seq and logs_parallel == logs_seq else "FAIL"
        self.report.add_result("Deterministic Replay", len(sequence), len(parallel_accepted), 0, "Hash Match", status)
        print(f"Result: {status}")
        if status == "FAIL":
            print(f"Parallel Hash: {hash_parallel} | Seq Hash: {hash_seq}")
            print(f"Parallel Logs: {logs_parallel}")
            print(f"Seq Logs: {logs_seq}")
            print(f"Accepted IDs: {parallel_accepted}")

    def run_all(self):
        print("\n--- STARTING BRUTAL SIMULATION ---")
        self.run_concurrency_test()
        self.run_storm_test()
        self.run_zombie_flood()
        self.run_shuffle_test()
        self.run_fuzz_test()
        self.run_deterministic_replay()
        
        self.report.print_matrix()

if __name__ == "__main__":
    sim = BrutalSimulator()
    sim.run_all()
