import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("firma.narrator")

class Narrator:
    """
    The Narrator translates technical state changes and data dumps into 
    a readable human story. No emojis, just clear narrative markers.
    """
    
    @staticmethod
    def run_bootstrapped(run_id: str, config: Dict[str, Any]):
        project_name = config.get("project_name", "Unknown Project")
        plan_name = config.get("plan_name", "Initial Plan")
        logger.info(f"[RUN] Bootstrapped new run {run_id} | Project: {project_name} | Plan: {plan_name}")

    @staticmethod
    def run_started(run_id: str):
        logger.info(f"[RUN] Execution started for run {run_id}")

    @staticmethod
    def run_stopped(run_id: str, status: str):
        logger.info(f"[RUN] Run {run_id} has reached terminal state: {status}")

    @staticmethod
    def phase_change(phase_name: str):
        logger.info(f"\n{'='*20} CURRENT PHASE: {phase_name} {'='*20}\n")

    @staticmethod
    def task_assigned(task_id: str, role: str, run_id: str):
        logger.info(f"[TASK] Task {task_id} assigned to {role} (Run {run_id})")

    @staticmethod
    def worker_response(task_id: str, event: str, role: str, run_id: str):
        logger.info(f"[EVENT] Worker {role} submitted {event} for Task {task_id} (Run {run_id})")

    @staticmethod
    def transition(task_id: str, from_phase: str, to_phase: str, event: str):
        logger.info(f"[TRANSITION] Task {task_id}: {from_phase} -> {to_phase} via {event}")

    @staticmethod
    def system_action(action: str, task_id: Optional[str] = None, details: Optional[str] = None):
        msg = f"[SYSTEM] {action}"
        if task_id:
            msg += f" for Task {task_id}"
        if details:
            msg += f" | {details}"
        logger.info(msg)

    @staticmethod
    def failure(task_id: str, reason: str, run_id: str, terminal: bool = False):
        prefix = "[TERMINAL FAILURE]" if terminal else "[FAILURE]"
        logger.error(f"{prefix} Task {task_id} failed: {reason} (Run {run_id})")

    @staticmethod
    def slow_warning(task_id: str, elapsed_seconds: int):
        logger.info(f"[SYSTEM] Task {task_id} is responding slowly ({elapsed_seconds}s elapsed). Waiting for timeout.")

    @staticmethod
    def provider_call(provider: str, model: str, task_id: str):
        logger.debug(f"[PROVIDER] Calling {provider} with model {model} for Task {task_id}")

    @staticmethod
    def provider_result(provider: str, latency_ms: float, success: bool):
        status = "SUCCESS" if success else "FAILED"
        logger.debug(f"[PROVIDER] {provider} returned in {latency_ms:.2f}ms | Status: {status}")
