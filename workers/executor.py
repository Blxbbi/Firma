import logging
import json
import time
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field, ValidationError
from engine.providers.base import BaseLLMProvider
from engine.models import Message, MessageHeader, MessageType, WorkerResponse
from engine.exceptions import WorkerExecutionError

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("firma.audit")

class FileArtifact(BaseModel):
    path: str
    action: str # CREATE, UPDATE, DELETE
    content: str

class ExecutorLLMOutput(BaseModel):
    artifacts: Dict[str, List[FileArtifact]] = Field(
        description="A dictionary containing a 'files' key with a list of file changes."
    )
    logs: Optional[str] = None
    thinking: Optional[str] = None

class ExecutionWorker:
    """
    ExecutionWorker: A strict adapter that converts a TASK_ASSIGNMENT into a TASK_RESULT.
    
    Rules:
    1. Pure IO: No DB access, no filesystem access.
    2. No Auto-Fix: Invalid JSON or Schema violations result in ERROR_REPORT.
    3. No Retries: The worker does not retry; the Engine decides.
    """

    def __init__(self, provider: BaseLLMProvider, model_name: str, dummy_mode: bool = False):
        self.provider = provider
        self.model_name = model_name
        self.dummy_mode = dummy_mode

    async def handle_assignment(self, project_id: str, plan_id: str, task_id: str, task_definition: Dict[str, Any], global_goal: str = "") -> Message:
        """
        Processes a task assignment and generates the corresponding artifacts.
        Enforces the strict Guardian Contract: artifacts must be a list of files.
        """
        logger.info(f"[Worker] RECEIVED ASSIGNMENT: task={task_id}")
        if self.dummy_mode:
            logger.info(f"[DUMMY MODE] Generating Golden Sample for task {task_id}")
            
            # Golden Sample HTML: High-End Corporate Dark Theme
            golden_html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Firma | Deterministic AI Execution</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;800&display=swap');
        body { font-family: 'Inter', sans-serif; }
        .glass { background: rgba(15, 23, 42, 0.8); backdrop-filter: blur(12px); }
        .gradient-text { background: linear-gradient(45deg, #38bdf8, #818cf8); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
    </style>
</head>
<body class="bg-slate-950 text-slate-100 selection:bg-sky-500/30">
    <nav class="fixed top-0 w-full z-50 glass border-b border-slate-800">
        <div class="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
            <div class="flex items-center gap-3">
                <svg width="32" height="32" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <rect width="32" height="32" rx="8" fill="#0f172a"/>
                    <circle cx="16" cy="16" r="6" stroke="#38bdf8" stroke-width="2"/>
                    <path d="M16 4V10M16 22V28M4 16H10M22 16H28" stroke="#818cf8" stroke-width="2" stroke-linecap="round"/>
                </svg>
                <span class="text-xl font-extrabold tracking-tight">FIRMA</span>
            </div>
            <div class="hidden md:flex items-center gap-8 text-sm font-medium text-slate-400">
                <a href="#architecture" class="hover:text-white transition-colors">Architecture</a>
                <a href="#governance" class="hover:text-white transition-colors">Governance</a>
                <a href="#vision" class="hover:text-white transition-colors">Vision</a>
                <a href="#" class="px-4 py-2 bg-sky-600 text-white rounded-full hover:bg-sky-500 transition-all">Documentation</a>
            </div>
        </div>
    </nav>

    <section class="relative pt-32 pb-20 px-6">
        <div class="max-w-5xl mx-auto text-center">
            <div class="inline-block px-3 py-1 mb-6 text-xs font-semibold tracking-wider text-sky-400 uppercase bg-sky-400/10 rounded-full border border-sky-400/20">
                Runtime v1.0 Now Active
            </div>
            <h1 class="text-5xl md:text-7xl font-extrabold tracking-tighter mb-6">
                The <span class="gradient-text">Deterministic Kernel</span><br>for Probabilistic Compute
            </h1>
            <p class="text-lg md:text-xl text-slate-400 max-w-3xl mx-auto mb-10 leading-relaxed">
                Firma transforms the unpredictability of Large Language Models into industrial-grade execution. 
                We wrap probabilistic intelligence in a deterministic governance layer.
            </p>
            <div class="flex flex-col sm:flex-row items-center justify-center gap-4">
                <a href="#" class="w-full sm:w-auto px-8 py-4 bg-white text-slate-950 font-bold rounded-xl hover:bg-slate-200 transition-all">Get Started</a>
                <a href="#" class="w-full sm:w-auto px-8 py-4 bg-slate-900 text-white font-bold rounded-xl border border-slate-800 hover:bg-slate-800 transition-all">Read Whitepaper</a>
            </div>
        </div>
    </section>

    <section id="architecture" class="py-24 px-6 bg-slate-900/50 border-y border-slate-800">
        <div class="max-w-7xl mx-auto">
            <div class="text-center mb-16">
                <h2 class="text-3xl md:text-4xl font-bold mb-4">System Architecture</h2>
                <p class="text-slate-400">A tripartite division of cognitive labor.</p>
            </div>
            <div class="grid md:grid-cols-3 gap-8">
                <div class="p-8 rounded-3xl bg-slate-950 border border-slate-800 hover:border-sky-500/50 transition-all group">
                    <div class="w-12 h-12 mb-6 rounded-xl bg-sky-500/10 flex items-center justify-center group-hover:scale-110 transition-transform">
                        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#38bdf8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M9 9h6v6H9z"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2"/></svg>
                    </div>
                    <h3 class="text-xl font-bold mb-3">The Kernel</h3>
                    <p class="text-slate-400 text-sm leading-relaxed">The brain. Manages state transitions, maintains the Plan Registry, and enforces structural governance. No action occurs without Kernel approval.</p>
                </div>
                <div class="p-8 rounded-3xl bg-slate-950 border border-slate-800 hover:border-indigo-500/50 transition-all group">
                    <div class="w-12 h-12 mb-6 rounded-xl bg-indigo-500/10 flex items-center justify-center group-hover:scale-110 transition-transform">
                        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#818cf8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12h20M12 2v20M5 12l7 7 7-7"/></svg>
                    </div>
                    <h3 class="text-xl font-bold mb-3">Nervous System</h3>
                    <p class="text-slate-400 text-sm leading-relaxed">pi-messenger. The high-speed transport layer that routes tasks, collects artifacts, and synchronizes the distributed worker mesh.</p>
                </div>
                <div class="p-8 rounded-3xl bg-slate-950 border border-slate-800 hover:border-emerald-500/50 transition-all group">
                    <div class="w-12 h-12 mb-6 rounded-xl bg-emerald-500/10 flex items-center justify-center group-hover:scale-110 transition-transform">
                        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
                    </div>
                    <h3 class="text-xl font-bold mb-3">The Muscles</h3>
                    <p class="text-slate-400 text-sm leading-relaxed">LLM Workers. Probabilistic engines tasked with generating code and content, strictly constrained by the Kernel's deterministic guards.</p>
                </div>
            </div>
        </div>
    </section>

    <section id="governance" class="py-24 px-6">
        <div class="max-w-4xl mx-auto text-center">
            <h2 class="text-3xl md:text-4xl font-bold mb-6">Governance by Design</h2>
            <p class="text-slate-400 mb-12">We don't hope for correctness. We enforce it through a closed-loop validation pipeline.</p>
            <div class="relative p-1 bg-gradient-to-r from-sky-500 via-indigo-500 to-emerald-500 rounded-2xl">
                <div class="bg-slate-950 rounded-2xl p-8 text-left">
                    <div class="grid gap-6">
                        <div class="flex items-start gap-4">
                            <div class="w-6 h-6 rounded-full bg-sky-500 flex-shrink-0 flex items-center justify-center text-[10px] font-bold">1</div>
                            <div><strong class="block text-white">Planning</strong><span class="text-slate-400 text-sm">Decomposing goals into a deterministic state-machine.</span></div>
                        </div>
                        <div class="flex items-start gap-4">
                            <div class="w-6 h-6 rounded-full bg-indigo-500 flex-shrink-0 flex items-center justify-center text-[10px] font-bold">2</div>
                            <div><strong class="block text-white">Implementation</strong><span class="text-slate-400 text-sm">Parallel execution via isolated probabilistic workers.</span></div>
                        </div>
                        <div class="flex items-start gap-4">
                            <div class="w-6 h-6 rounded-full bg-emerald-500 flex-shrink-0 flex items-center justify-center text-[10px] font-bold">3</div>
                            <div><strong class="block text-white">Validation</strong><span class="text-slate-400 text-sm">Hard-coded structural checks before artifact acceptance.</span></div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </section>

    <section id="vision" class="py-24 px-6 bg-slate-900/30 border-t border-slate-800">
        <div class="max-w-3xl mx-auto text-center">
            <h2 class="text-3xl font-bold mb-6">Our Vision</h2>
            <p class="text-slate-400 leading-relaxed">
                To create a world where AI isn't a black box of "maybe", but a reliable component of a larger, deterministic system. 
                Firma is the foundation for this evolution.
            </p>
        </div>
    </section>

    <footer class="py-12 px-6 border-t border-slate-800 text-center">
        <div class="max-w-7xl mx-auto flex flex-col md:flex-row justify-between items-center gap-6">
            <div class="flex items-center gap-3">
                <svg width="20" height="20" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <rect width="32" height="32" rx="8" fill="#0f172a"/>
                    <circle cx="16" cy="16" r="6" stroke="#38bdf8" stroke-width="2"/>
                </svg>
                <span class="font-bold text-slate-300">FIRMA KERNEL</span>
            </div>
            <div class="text-slate-500 text-xs">
                &copy; 2026 Firma Runtime. Determinism as a Service.
            </div>
        </div>
    </footer>
</body>
</html>"""
            
            dummy_artifacts = {
                "files": [
                    {
                        "path": "index.html",
                        "action": "CREATE",
                        "content": golden_html
                    },
                    {
                        "path": "styles.css",
                        "action": "CREATE",
                        "content": "/* Styles are handled by Tailwind CDN in index.html */"
                    },
                    {
                        "path": "script.js",
                        "action": "CREATE",
                        "content": "console.log('Firma Runtime: Website Loaded');"
                    }
                ]
            }
            
            # Process through the same normalization logic as a real worker
            # Convert to FileArtifact objects for normalization
            artifacts_objs = [FileArtifact(**f) for f in dummy_artifacts["files"]]
            normalized_files = self._normalize_artifacts(artifacts_objs)
            
            return Message(
                header=MessageHeader(
                    sender="execution-worker",
                    recipient="engine",
                    message_type=MessageType.WORKER_RESPONSE,
                    plan_id=plan_id
                ),
                payload={
                    "project_id": project_id,
                    "run_id": project_id,
                    "task_id": task_id,
                    "event": "CODE_SUBMITTED",
                    "sender_role": "CODER",
                    "artifacts": normalized_files,
                    "logs": "Golden sample artifacts generated."
                }
            )
        
        system_prompt = (
            "You are the Firma Execution Worker. Your role is to implement a SPECIFIC TASK that is part of a LARGER PROJECT.\n\n"
            "STRICT OUTPUT CONTRACT:\n"
            "You MUST return a JSON object. The 'artifacts' field MUST be a dictionary containing a 'files' list.\n"
            "Each file object MUST contain: 'path', 'action' (CREATE, UPDATE, or DELETE), and 'content'.\n\n"
            "CRITICAL LANGUAGE RULE: Follow the project's language requirements strictly. "
            "If the project is a Web App (HTML/CSS/JS), DO NOT produce Python code, requirements.txt, or any other file types unless explicitly requested.\n\n"
            "ANTI-LAZINESS DIRECTIVE:\n"
            "- DO NOT return empty templates, placeholders (e.g. '// Add your code here'), or skeleton files.\n"
            "- The code MUST be fully functional and implement the complete logic required by the task.\n"
            "- A non-working or stub implementation will be REJECTED by the verifier.\n\n"
            "Example Format (Web App):\n"
            "{\n"
            "  \"artifacts\": {\n"
            "    \"files\": [\n"
            "      {\"path\": \"index.html\", \"action\": \"CREATE\", \"content\": \"<canvas id='game'></canvas>\"},\n"
            "      {\"path\": \"style.css\", \"action\": \"CREATE\", \"content\": \"body { margin: 0; }\"},\n"
            "      {\"path\": \"game.js\", \"action\": \"CREATE\", \"content\": \"const canvas = document.getElementById('game');\"}\n"
            "    ]\n"
            "  }\n"
            "}\n\n"
            "Do not include any explanations, markdown, or extra keys. Return ONLY the JSON."
        )

        
        # Merge Global Project Goal with Specific Subtask Context
        task_desc = task_definition.get('description', 'N/A') if isinstance(task_definition, dict) else str(task_definition)
        task_crit = task_definition.get('acceptance_criteria', []) if isinstance(task_definition, dict) else []
        
        user_prompt = (
            f"=== GLOBAL PROJECT GOAL ===\n"
            f"{global_goal if global_goal else 'Implement the requested software project.'}\n\n"
            f"=== YOUR SPECIFIC SUBTASK (Part of the project above) ===\n"
            f"Task Description: {task_desc}\n"
            f"Acceptance Criteria: {task_crit}\n\n"
            "=== VERIFIER EXPECTATIONS (Your output will be rejected if these fail) ===\n"
            "- If this is a web game, index.html MUST contain a <canvas> tag.\n"
            "- game.js MUST contain 'addEventListener' for keyboard input and a game loop (requestAnimationFrame or setInterval).\n"
            "- The game MUST be playable: snake moves, food spawns, snake grows, collision ends game.\n\n"
            "=== YOUR ACTION ===\n"
            "Implement the required artifacts strictly following the acceptance criteria. "
            "Ensure each file has a clear 'action' (CREATE/UPDATE/DELETE). "
            "Write COMPLETE, WORKING code. No placeholders."
        )
        
        # Use the ExecutorLLMOutput schema for structural determinism
        schema = ExecutorLLMOutput.model_json_schema()
        
        logger.info(f"[Worker] ABOUT TO CALL PROVIDER: task={task_id} model={self.model_name}")
        start_time = time.time()
        try:
            # 1. Generate JSON via Provider
            raw_output = await self.provider.generate_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema=schema
            )
            logger.info(f"[Worker] PROVIDER CALL RETURNED: task={task_id} latency={time.time()-start_time:.2f}s")
            latency = time.time() - start_time
            
            # 2. Strict Validation
            validated_response = ExecutorLLMOutput.model_validate(raw_output)
            
            # 2b. Deterministic Normalization (Adapter Layer)
            normalized_files = self._normalize_artifacts(validated_response.artifacts.get("files", []))
            
            # Audit Log
            self._log_audit(user_prompt, raw_output, latency, None)
            
            # 3. Success Message: Use normalized files to satisfy Kernel Contract
            return Message(
                header=MessageHeader(
                    sender="execution-worker",
                    recipient="engine",
                    message_type=MessageType.WORKER_RESPONSE,
                    plan_id=plan_id
                ),
                payload={
                    "project_id": project_id,
                    "run_id": project_id,
                    "task_id": task_id,
                    "event": "CODE_SUBMITTED",
                    "sender_role": "CODER",
                    "artifacts": normalized_files,
                    "logs": "Artifacts successfully generated."
                }
            )

        except ValidationError as e:
            latency = time.time() - start_time
            self._log_audit(user_prompt, "ValidationError", latency, str(e))
            return self._create_error_report(project_id, plan_id, task_id, "SCHEMA_VIOLATION", str(e))
        except WorkerExecutionError:
            # Let this propagate to the worker loop for deterministic governance mapping
            raise
        except Exception as e:
            latency = time.time() - start_time
            self._log_audit(user_prompt, "Exception", latency, str(e))
            return self._create_error_report(project_id, plan_id, task_id, "LLM_INTERNAL_ERROR", str(e))

    def _normalize_artifacts(self, artifacts: List[FileArtifact]) -> List[Dict[str, Any]]:
        """
        Deterministic Adapter: Ensures LLM output complies with Kernel Null-Semantics.
        - DELETE action MUST have content=None.
        - CREATE/UPDATE action MUST have content as string.
        """
        normalized = []
        for art in artifacts:
            item = art.model_dump()
            action = item["action"]
            
            if action == "DELETE":
                if item.get("content") is not None:
                    logger.info(f"[Normalizer] DELETE detected for {item['path']} -> forcing content=None (LLM sent: {repr(item.get('content'))})")
                item["content"] = None
            elif action in ("CREATE", "UPDATE"):
                if item.get("content") is None:
                    # This is a structural failure, not a normalization opportunity
                    raise ValueError(f"Artifact {item['path']} with action {action} must have content.")
            
            normalized.append(item)
        return normalized

    def _create_error_report(self, project_id: str, plan_id: str, task_id: str, error_code: str, detail: str) -> Message:
        return Message(
            header=MessageHeader(
                sender="execution-worker",
                recipient="engine",
                message_type=MessageType.WORKER_RESPONSE,
                plan_id=plan_id
            ),
            payload={
                "project_id": project_id,
                "run_id": project_id,
                "task_id": task_id,
                "event": "TASK_FAILED",
                "sender_role": "CODER",
                "logs": f"Error {error_code}: {detail}"
            }
        )

    def _log_audit(self, prompt: str, output: Any, latency: float, error: Optional[str]):
        audit_logger.info(
            f"EXECUTION_AUDIT | model: {self.model_name} | latency: {latency:.2f}s | "
            f"error: {error} | prompt: {prompt[:100]}... | output: {str(output)[:500]}"
        )
