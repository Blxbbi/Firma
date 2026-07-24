import logging
import json
import time
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List
from pydantic import ValidationError
from engine.providers.base import BaseLLMProvider
from engine.models import Message, MessageHeader, MessageType, WorkerResponse, TaskEvent
from engine.exceptions import WorkerExecutionError

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("firma.audit")


class ResearcherWorker:
    """
    ResearcherWorker: Read-only explorer that produces a research brief for the Planner.
    
    Rules:
    1. Pure IO: No DB access, no state mutation.
    2. Read-only: Must NOT modify project files. Only writes research/brief.md + worker_response.
    3. No Auto-Fix: Invalid JSON or Schema violations result in ERROR_REPORT.
    4. No Retries: The worker does not retry; the Engine decides.
    """

    def __init__(self, provider: BaseLLMProvider, model_name: str, dummy_mode: bool = False):
        self.provider = provider
        self.model_name = model_name
        self.dummy_mode = dummy_mode

    async def handle_request(
        self,
        project_id: str,
        user_prompt: str,
        task_id: str,
        run_id: Optional[str] = None,
        project_root: Optional[str] = None,
    ) -> Message:
        """
        Processes a research request and produces:
        - research/brief.md (read-only findings with citations)
        - worker_response.<task_id>.response.json
        """
        logger.info(f"[Worker] RECEIVED RESEARCHER REQUEST: project={project_id} task={task_id}")

        if self.dummy_mode:
            logger.info("[Researcher] DUMMY_MODE active. Returning synthetic brief.")
            return self._dummy_response(project_id, task_id, run_id, user_prompt, project_root)


        # Build the research prompt
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(user_prompt, project_id, task_id, project_root)

        logger.info(f"[Worker] ABOUT TO CALL PROVIDER: project={project_id} model={self.model_name}")
        start_time = time.time()
        
        try:
            # Generate JSON via Provider
            raw_output = await self.provider.generate_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema=None,
            )
            logger.info(f"[Worker] PROVIDER CALL RETURNED: project={project_id} latency={time.time()-start_time:.2f}s")
            
            latency = time.time() - start_time
            
            # Parse and validate
            if not isinstance(raw_output, dict):
                raise ValueError(f"Expected dict, got {type(raw_output).__name__}")
            
            brief_markdown = raw_output.get("brief_markdown", "")
            if not brief_markdown:
                raise ValueError("Missing required field: brief_markdown")
            
            # Audit log
            self._log_audit(user_prompt, raw_output, latency, None)
            
            # Return response - the actual file writing happens in the task spec instructions
            return Message(
                header=MessageHeader(
                    sender="researcher-worker",
                    recipient="engine",
                    message_type=MessageType.WORKER_RESPONSE,
                ),
                payload={
                    "project_id": project_id,
                    "run_id": run_id,
                    "task_id": task_id,
                    "event": TaskEvent.RESEARCH_COMPLETE.value,
                    "sender_role": "RESEARCHER",
                    "artifacts": [
                        {
                            "path": "research/brief.md",
                            "action": "CREATE",
                            "content": brief_markdown,
                        }
                    ],
                    "logs": f"Research brief generated ({len(brief_markdown)} chars)",
                },
            )

        except ValidationError as e:
            latency = time.time() - start_time
            self._log_audit(user_prompt, "ValidationError", latency, str(e))
            return self._create_error_report(project_id, task_id, run_id, "SCHEMA_VIOLATION", str(e))
        except WorkerExecutionError:
            raise
        except Exception as e:
            latency = time.time() - start_time
            self._log_audit(user_prompt, "Exception", latency, str(e))
            return self._create_error_report(project_id, task_id, run_id, "LLM_INTERNAL_ERROR", str(e))

    def _build_system_prompt(self) -> str:
        return (
            "You are the Firma Researcher. Your role is to explore the project codebase "
            "and produce a structured research brief for the Planner.\n\n"
            "STRICT OUTPUT FORMAT:\n"
            "Return ONLY a valid JSON object with exactly these fields:\n"
            "{\n"
            '  "brief_markdown": "Full markdown brief with findings and recommendations"\n'
            "}\n\n"
            "RULES:\n"
            "1. Be factual. Only report what you actually find in the code.\n"
            "2. Use citations: file:path, line:number, evidence:exact_text\n"
            "3. Structure: Project Findings, Recommendations for Planner, Risks/Constraints\n"
            "4. Do NOT write code. Do NOT modify files. Research only.\n"
            "5. Keep it concise but complete — the Planner depends on it.\n"
        )

    def _build_user_prompt(
        self, user_prompt: str, project_id: str, task_id: str, project_root: Optional[str]
    ) -> str:
        parts = [
            f"Project ID: {project_id}",
            f"Task ID: {task_id}",
            f"User Goal: {user_prompt}",
        ]
        
        if project_root:
            parts.append(f"\nProject Root: {project_root}")
            parts.append(
                "\nExplore the project files under this root. "
                "Focus on understanding the existing structure, technologies, and patterns."
            )
        
        parts.append("\nProduce a research brief that will help the Planner create an accurate plan.")
        
        return "\n".join(parts)

    def _dummy_response(self, project_id: str, task_id: str, run_id: Optional[str], user_prompt: str, project_root: Optional[str]) -> Message:
        """Synthetic research brief for testing without LLM.

        The brief is built around the actual user prompt so the downstream Planner
        sees the real user goal, not a hardcoded template.
        """
        project_root = project_root or project_id
        root = Path(project_root)
        readme_candidates = ["README.md", "readme.md"]
        readme_hint = next((p.name for p in (root / name for name in readme_candidates) if p.exists()), "README.md")

        brief = f"""# Research Brief

## Project Findings
- file: {readme_hint} | line: 1 | evidence: project documentation
- file: docs/vision/PiMesh_Architektur.md | line: 1 | evidence: architecture documentation present
- file: engine/orchestrator.py | line: 1 | evidence: deterministic kernel implementation present

## Recommendations for Planner
- Use the user goal as primary source: {user_prompt}
- Create artifacts that satisfy this goal directly
- Base layout/content on project docs in project root: {project_root}
- Keep implementation portable and aligned with existing project conventions

## Risks/Constraints
- No existing target artifacts found yet; new implementation likely required
- Keep changes minimal and focused on the requested goal
- Ensure created files match the user-requested deliverable format
"""
        return Message(
            header=MessageHeader(
                sender="researcher-worker",
                recipient="engine",
                message_type=MessageType.WORKER_RESPONSE,
            ),
            payload={
                "project_id": project_id,
                "run_id": run_id,
                "task_id": task_id,
                "event": TaskEvent.RESEARCH_COMPLETE.value,
                "sender_role": "RESEARCHER",
                "artifacts": [
                    {
                        "path": "research/brief.md",
                        "action": "CREATE",
                        "content": brief,
                    }
                ],
                "logs": "Dummy research brief generated",
            },
        )

    def _create_error_report(
        self,
        project_id: str,
        task_id: str,
        run_id: Optional[str],
        error_code: str,
        detail: str,
    ) -> Message:
        return Message(
            header=MessageHeader(
                sender="researcher-worker",
                recipient="engine",
                message_type=MessageType.WORKER_RESPONSE,
            ),
            payload={
                "project_id": project_id,
                "run_id": run_id,
                "task_id": task_id,
                "event": TaskEvent.TASK_FAILED.value,
                "sender_role": "RESEARCHER",
                "error_code": error_code,
                "logs": f"Error {error_code}: {detail}",
            },
        )

    def _log_audit(self, prompt: str, output: Any, latency: float, error: Optional[str]):
        audit_logger.info(
            f"RESEARCHER_AUDIT | model: {self.model_name} | latency: {latency:.2f}s | "
            f"error: {error} | prompt: {prompt[:100]}... | output: {str(output)[:500]}"
        )
