import time
import logging
from sqlalchemy.orm import Session
from .repository import MessageRepository
from .models import Task

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TimeoutManager")

class TimeoutManager:
    """
    Handles task timeouts and automatic retries.
    Prevents tasks from hanging in CLAIMED or IN_PROGRESS forever.
    """
    def __init__(self, repo: MessageRepository, timeout_seconds: int = 300):
        self.repo = repo
        self.timeout_seconds = timeout_seconds

    def check_and_retry_overdue_tasks(self):
        """
        Scans for overdue tasks and resets them to READY.
        """
        logger.info("Scanning for overdue tasks...")
        overdue_tasks = self.repo.get_overdue_tasks(self.timeout_seconds)
        
        for task in overdue_tasks:
            logger.warning(f"Task {task.id} is overdue (State: {task.state}). Triggering retry...")
            
            # Increment retry count
            task.retry_count += 1
            
            if task.retry_count >= task.max_retries:
                logger.error(f"Task {task.id} reached max retries. Setting to FAILED.")
                self.repo.update_task_state(task.id, "FAILED")
            else:
                logger.info(f"Resetting Task {task.id} to READY. Retry count: {task.retry_count}")
                self.repo.update_task_state(task.id, "READY")
        
        # Since we modified task objects directly, we need to commit via repo's session
        self.repo.db.commit()
        logger.info(f"Checked {len(overdue_tasks)} overdue tasks.")

    def run_loop(self, interval_seconds: int = 60):
        """
        Starts a blocking loop to manage timeouts.
        """
        logger.info(f"Timeout Manager started. Interval: {interval_seconds}s, Timeout: {self.timeout_seconds}s")
        while True:
            try:
                self.check_and_retry_overdue_tasks()
            except Exception as e:
                logger.error(f"Error in timeout loop: {e}")
            time.sleep(interval_seconds)
