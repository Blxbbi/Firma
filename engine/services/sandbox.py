import asyncio
import os
import tempfile
import shutil
import logging
import time
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Optional
from abc import ABC, abstractmethod
from engine.services.telemetry import telemetry

logger = logging.getLogger(__name__)

@dataclass
class ExecutionResult:
    exit_code: Optional[int]
    stdout: str
    stderr: str
    timed_out: bool

class SandboxExecutor(ABC):
    """Abstract base for deterministic code execution."""
    @abstractmethod
    async def run(self, files: List[Dict[str, str]], command: str, timeout: float) -> ExecutionResult:
        pass

    @abstractmethod
    async def run_command(self, command_args: List[str], workspace: Path) -> ExecutionResult:
        """Executes a command in an existing workspace."""
        pass

class LocalPythonSandbox(SandboxExecutor):
    """
    A minimalist local Python sandbox.
    Provides filesystem isolation via TemporaryDirectory and 
    execution isolation via asyncio subprocess.
    """
    async def run_command(self, command_args: List[str], workspace: Path) -> ExecutionResult:
        t0 = time.perf_counter_ns()
        try:
            # Windows Compatibility: Ensure python scripts are run with the python interpreter
            if os.name == "nt" and command_args and command_args[0].endswith(".py"):
                command_args = ["python", *command_args]

            # We use the provided workspace directory for execution
            process = await asyncio.create_subprocess_exec(
                *command_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(workspace)
            )
            stdout, stderr = await process.communicate()

            exit_code = process.returncode
            
            res = ExecutionResult(
                exit_code=exit_code,
                stdout=stdout.decode(errors="replace"),
                stderr=stderr.decode(errors="replace"),
                timed_out=False
            )
            telemetry.observe("sandbox_cmd_latency_ns", time.perf_counter_ns() - t0)
            return res
        except Exception as e:
            logger.exception(f"Sandbox command error: {e}")
            return ExecutionResult(exit_code=1, stdout="", stderr=str(e), timed_out=False)

    async def run(self, files: List[Dict[str, str]], command: str, timeout: float = 5.0) -> ExecutionResult:

        t0 = time.perf_counter_ns()
        # 1. FS Isolation: Create a strictly isolated temporary workspace
        with tempfile.TemporaryDirectory(prefix="firma_sandbox_") as tmp_dir:
            # Measure startup separately if needed, but for now, total run is fine.
            # To be precise, we'll mark the 'start' of actual execution.
            logger.debug(f"Sandbox workspace created at {tmp_dir}")
            
            # 2. Materialize Artifacts
            for file_data in files:
                path = os.path.join(tmp_dir, file_data["path"])
                # Prevent directory traversal attacks
                if not os.path.abspath(path).startswith(os.path.abspath(tmp_dir)):
                    logger.error(f"Security Alert: Attempted path traversal in artifact {file_data['path']}")
                    telemetry.observe("sandbox_exec_latency_ns", time.perf_counter_ns() - t0)
                    return ExecutionResult(exit_code=1, stdout="", stderr="Path traversal detected", timed_out=False)
                
                with open(path, "w", encoding="utf-8") as f:
                    f.write(file_data["content"])

            # 3. Execution: Non-blocking subprocess
            try:
                # Robust Observation Level: Use absolute Path resolve() for snapshotting
                workspace = Path(tmp_dir).resolve()
                parent = workspace.parent
                
                # Initial state: Absolute paths of all items in the parent directory
                files_before = {p.resolve() for p in parent.iterdir()}

                # We execute the command inside the tmp_dir
                t_start_exec = time.perf_counter_ns()
                
                cmd_args = command.split() if isinstance(command, str) else command
                
                # Windows Compatibility: Ensure python scripts are run with the python interpreter
                if os.name == "nt" and cmd_args and cmd_args[0].endswith(".py"):
                    cmd_args = ["python", *cmd_args]
                    
                process = await asyncio.create_subprocess_exec(
                    *cmd_args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=tmp_dir
                )
                telemetry.observe("sandbox_startup_latency_ns", time.perf_counter_ns() - t_start_exec)

                try:
                    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
                    exit_code = process.returncode
                    timed_out = False
                except asyncio.TimeoutError:
                    logger.warning(f"Sandbox execution timed out after {timeout}s. Killing process...")
                    try:
                        process.kill()
                        stdout, stderr = await process.communicate()
                    except Exception as e:
                        stdout, stderr = b"", f"Error during kill: {e}".encode()
                    
                    exit_code = -1
                    timed_out = True

                # POST-EXECUTION SECURITY CHECK: Absolute Path Snapshot-Diff
                files_after = {p.resolve() for p in parent.iterdir()}
                new_files = files_after - files_before
                
                # A leak is any new file in the parent that is NOT inside the workspace
                leaks = [p for p in new_files if not p.is_relative_to(workspace)]
                
                # Filter noise: ignore common system temp files (e.g., starting with . or ending with .tmp)
                actual_leaks = [p for p in leaks if not (p.name.startswith('.') or p.name.endswith('.tmp'))]

                if actual_leaks:
                    # Immediate cleanup of detected leaks to prevent state contamination
                    for leak_path in actual_leaks:
                        try:
                            if leak_path.is_file():
                                leak_path.unlink()
                            elif leak_path.is_dir():
                                shutil.rmtree(leak_path)
                        except Exception as e:
                            logger.warning(f"Failed to clean up leak {leak_path}: {e}")
                    
                    logger.error(f"Security Alert: Sandbox escape detected! Leaks: {[p.name for p in actual_leaks]}")
                    telemetry.observe("sandbox_exec_latency_ns", time.perf_counter_ns() - t0)
                    return ExecutionResult(
                        exit_code=2, 
                        stdout=stdout.decode(errors="replace"), 
                        stderr=f"Security violation: Files created outside sandbox workspace: {[p.name for p in actual_leaks]}", 
                        timed_out=timed_out
                    )

                res = ExecutionResult(
                    exit_code=exit_code,
                    stdout=stdout.decode(errors="replace"),
                    stderr=stderr.decode(errors="replace"),
                    timed_out=timed_out
                )
                telemetry.observe("sandbox_exec_latency_ns", time.perf_counter_ns() - t0)
                return res

            except Exception as e:
                telemetry.observe("sandbox_exec_latency_ns", time.perf_counter_ns() - t0)
                logger.exception(f"Sandbox internal error: {e}")
                return ExecutionResult(exit_code=1, stdout="", stderr=str(e), timed_out=False)

# Alias for backward compatibility
Sandbox = SandboxExecutor
