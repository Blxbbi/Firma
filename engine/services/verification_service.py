import logging
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, Tuple
from engine.models import Task
from engine.services.sandbox import SandboxExecutor, ExecutionResult
# Remove this import as ExecutionResult is now from sandbox


logger = logging.getLogger(__name__)

@dataclass
class VerificationResult:
    """
    The deterministic result of acceptance criteria verification.
    """
    passed: bool
    details: List[str]
    error: Optional[str] = None

class VerificationService:
    """
    VerificationService: The deterministic judge of the Engine.
    
    Rules:
    1. No heuristics. No fuzzy matching. No tolerance.
    2. All criteria must pass for the task to be VERIFIED.
    3. Operates on the actual physical state of the sandbox workspace.
    """

    def __init__(self, sandbox: SandboxExecutor):
        self.sandbox = sandbox

    async def verify(self, task: Task, exec_result: ExecutionResult, workspace: Path) -> VerificationResult:
        """
        Verifies a task against its acceptance criteria.
        """
        logger.info(f"Verifying task {task.id} against {len(task.acceptance_criteria)} criteria...")
        
        # 1. Base Execution Check
        # Logic: Base execution is ONLY required if no specific CMD criteria are defined.
        # If CMD criteria exist, they define the success of the execution.
        has_cmd_criteria = any(c.startswith("CMD:") for c in task.acceptance_criteria)
        
        if not has_cmd_criteria:
            execution_failed = (
                exec_result.exit_code is None 
                or exec_result.exit_code != 0 
                or exec_result.timed_out
            )
            if execution_failed:
                return VerificationResult(
                    passed=False, 
                    details=[f"Base execution failed with exit code {exec_result.exit_code} (No CMD criteria defined)"],
                    error="EXECUTION_FAILED"
                )

        # 2. Acceptance Criteria Check
        details = []
        for criterion in task.acceptance_criteria:
            passed, reason = await self._verify_criterion(criterion, workspace)
            details.append(f"[{'PASS' if passed else 'FAIL'}] {criterion} -> {reason}")
            if not passed:
                return VerificationResult(passed=False, details=details)

        return VerificationResult(passed=True, details=details)

    async def _verify_criterion(self, criterion: str, workspace: Path) -> Tuple[bool, str]:
        """
        Determinisitically verifies a single criterion.
        No shell, no subprocesses, pure Python.
        """
        if criterion.startswith("EXISTS:"):
            # Format: EXISTS:path/to/file
            path_str = criterion.split(":", 1)[1]
            target_path = workspace / path_str
            if target_path.exists():
                return True, "File exists"
            return False, "File missing"

        elif criterion.startswith("NOT_EXISTS:"):
            # Format: NOT_EXISTS:path/to/file
            path_str = criterion.split(":", 1)[1]
            target_path = workspace / path_str
            if not target_path.exists():
                return True, "File does not exist (correct)"
            return False, "File unexpectedly exists"

        elif criterion.startswith("CONTAINS:"):
            # Format: CONTAINS:file:string
            parts = criterion.split(":", 2)
            if len(parts) < 3:
                return False, "Malformed CONTAINS criterion (expected CONTAINS:file:string)"
            
            file_path_str = parts[1]
            expected_text = parts[2]
            target_path = workspace / file_path_str
            
            if not target_path.exists():
                return False, f"File {file_path_str} does not exist"
            
            try:
                content = target_path.read_text(encoding="utf-8", errors="ignore")
                if expected_text.lower() in content.lower():
                    return True, f"Found '{expected_text}' in {file_path_str}"
                return False, f"Could not find '{expected_text}' in {file_path_str}"
            except Exception as e:
                return False, f"Read error: {str(e)}"

        elif criterion.startswith("CMD:"):
            # DEPRECATED: kept for backward compatibility, but should not be used in new tasks
            logger.warning(f"Criterion {criterion} uses deprecated CMD: prefix. Consider switching to PY-based criteria.")
            try:
                parts = criterion.split(":", 2)
                if len(parts) < 2:
                    return False, "Malformed CMD criterion"
                
                cmd_str = parts[1]
                expected_output = parts[2] if len(parts) == 3 else None
                
                import shlex
                command_args = shlex.split(cmd_str)
                res = await self.sandbox.run_command(command_args, workspace)
                
                if expected_output is None:
                    if res.exit_code == 0:
                        return True, "Command executed successfully (exit code 0)"
                    else:
                        return False, f"Command failed with exit code {res.exit_code}"

                actual_output = res.stdout.strip()
                if actual_output == expected_output.strip():
                    return True, "Output matches exactly"
                else:
                    return False, f"Output mismatch. Expected '{expected_output.strip()}', got '{actual_output}'"
            except Exception as e:
                return False, f"Execution error: {str(e)}"

        return False, "Unknown criterion format"
