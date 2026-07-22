import queue
import threading
import time
import logging
import os
import tempfile
from typing import Optional, Callable
from sqlalchemy.orm import Session, sessionmaker
from engine.db import Session as DB_Session, init_db, engine as global_engine
from engine.workflow import process_message_workflow
from engine.scheduler import Scheduler
from engine.models import Message, MessageType, Plan, Task, MessageLog
from engine.repository import MessageRepository

logger = logging.getLogger(__name__)

class InMemoryMessenger:
    def __init__(self):
        self.engine_queue = queue.Queue()
        self.worker_queue = queue.Queue()

    def send_to_engine(self, message: Message):
        self.engine_queue.put(message)

    def send_to_worker(self, message: Message):
        self.worker_queue.put(message)

    def receive_from_engine(self, timeout=None):
        try:
            return self.engine_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def receive_from_worker(self, timeout=None):
        try:
            return self.worker_queue.get(timeout=timeout)
        except queue.Empty:
            return None

class InfrastructureTestHarness:
    def __init__(self, worker_mode: str = "happy", scheduler_interval: float = 0.05):
        self.messenger = InMemoryMessenger()
        self.worker_mode = worker_mode
        self.scheduler_interval = scheduler_interval
        
        self.db_session = None
        self.engine_thread = None
        self.scheduler_thread = None
        self.worker_thread = None
        self.running = False
        self.temp_db_path = None

    def setup(self):
        # Create a temporary file for the database to avoid locking and persistence issues
        fd, self.temp_db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        
        # Use a new engine and a new scoped_session for the test
        from sqlalchemy import create_engine
        from sqlalchemy.orm import scoped_session
        from engine.models import Base
        
        self.test_engine = create_engine(f"sqlite:///{self.temp_db_path}", connect_args={"check_same_thread": False})
        self.test_session_factory = sessionmaker(bind=self.test_engine)
        self.db_session = scoped_session(self.test_session_factory)
        
        Base.metadata.create_all(bind=self.test_engine)

    def teardown(self):
        self.stop()
        if self.db_session:
            self.db_session.close()
        if self.temp_db_path and os.path.exists(self.temp_db_path):
            try:
                os.remove(self.temp_db_path)
            except:
                pass

    def start(self, worker_mode: str = "happy", scheduler_interval: float = 0.05):
        self.running = True
        self.worker_mode = worker_mode
        self.scheduler_interval = scheduler_interval
        
        # 1. Engine Thread
        def engine_loop():
            while self.running:
                msg = self.messenger.receive_from_engine(timeout=0.05)
                if msg:
                    self._engine_dispatch(msg)

        self.engine_thread = threading.Thread(target=engine_loop, daemon=True)
        self.engine_thread.start()

        # 2. Scheduler Thread
        def scheduler_loop():
            scheduler = Scheduler(self.db_session, messenger_callback=self.messenger.send_to_worker)
            while self.running:
                scheduler.run_tick()
                time.sleep(self.scheduler_interval)

        self.scheduler_thread = threading.Thread(target=scheduler_loop, daemon=True)
        self.scheduler_thread.start()

        # 3. Worker Thread
        from workers.dummy_worker import DummyWorker
        worker = DummyWorker(self.messenger.send_to_engine, mode=self.worker_mode)

        def worker_loop():
            while self.running:
                msg = self.messenger.receive_from_worker(timeout=0.05)
                if msg:
                    worker.handle_message(msg)

        self.worker_thread = threading.Thread(target=worker_loop, daemon=True)
        self.worker_thread.start()

    def stop(self):
        self.running = False
        if self.engine_thread: self.engine_thread.join()
        if self.scheduler_thread: self.scheduler_thread.join()
        if self.worker_thread: self.worker_thread.join()

    def _engine_dispatch(self, msg: Message):
        # Use the test session
        if msg.header.message_type == MessageType.PLAN_DRAFT_SUBMITTED:
            process_message_workflow(self.db_session, msg, task_id=None, event=None)
        else:
            task_id = msg.payload.get("task_id")
            event = msg.payload.get("event")
            process_message_workflow(self.db_session, msg, task_id=task_id, event=event)

    # --- Assertions ---
    def assert_task_state(self, task_id: str, expected_state: str):
        repo = MessageRepository(self.db_session)
        task = repo.get_task(task_id)
        if not task:
            raise AssertionError(f"Task {task_id} not found.")
        if task.state != expected_state:
            raise AssertionError(f"Task {task_id} state mismatch. Expected {expected_state}, got {task.state}")

    def assert_message_logged(self, msg_type: MessageType, status: str):
        repo = MessageRepository(self.db_session)
        logs = self.db_session.query(MessageLog).filter(
            MessageLog.message_type == msg_type.value,
            MessageLog.processing_status == status
        ).all()
        if not logs:
            raise AssertionError(f"No log entry found for {msg_type.value} with status {status}")

    def wait_for_task_state(self, task_id: str, expected_state: str, timeout=5.0):
        start = time.time()
        repo = MessageRepository(self.db_session)
        while time.time() - start < timeout:
            task = repo.get_task(task_id)
            if task and task.state == expected_state:
                return
            time.sleep(0.1)
        self.assert_task_state(task_id, expected_state)
