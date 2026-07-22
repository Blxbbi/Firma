import asyncio
import json
import os
import uuid
import logging
import sys
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple

from nats.aio.client import Client as NATS

# Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] CODER-AGENT: %(message)s'
)
logger = logging.getLogger("CoderAgent")

# ============================================================
# 1. The Black-Box Runtime (Provider Implementation)
# ============================================================

class LLMProvider(ABC):
    """Interface for LLM providers. The Agent is provider-agnostic."""
    @abstractmethod
    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        pass

class PiRuntimeLLM(LLMProvider):
    """
    The 'Compute-Node' implementation. 
    Direct OpenAI-compatible client to avoid LiteLLM abstraction hangs.
    """
    def __init__(self, model: str = "meta/llama-3.1-8b-instruct"):
        self.model = model

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        from openai import AsyncOpenAI
        
        api_key = os.getenv("NVIDIA_API_KEY") or os.getenv("OPENAI_API_KEY")
        base_url = "https://integrate.api.nvidia.com/v1" if os.getenv("NVIDIA_API_KEY") else None
        
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        
        try:
            # Direct call to OpenAI-compatible API
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.0,
                    response_format={ "type": "json_object" }
                ),
                timeout=40
            )
            content = response.choices[0].message.content
            logger.info(f"RAW LLM RESPONSE: {content}")
            return content
        except asyncio.TimeoutError:
            logger.error("Pi-Runtime LLM call timed out")
            raise RuntimeError("LLM_TIMEOUT")
        except Exception as e:
            logger.error(f"Pi-Runtime LLM error: {str(e)}")
            raise RuntimeError(f"LLM_PROVIDER_ERROR: {str(e)}")

class PiRuntime:
    """
    The Pi-Runtime object provided to the agent.
    Encapsulates all 'Compute-Layer' services.
    """
    def __init__(self, model: str = "gpt-4o"):
        self.llm = PiRuntimeLLM(model=model)

# ============================================================
# 2. The Agent (Pure Wire-Protocol Machine)
# ============================================================

class CoderAgent:
    """
    A Pi-integrated Agent that acts as a black-box worker for the Kernel.
    Communication: Strict NATS Wire-Protocol.
    Logic: No knowledge of 'engine', 'database', 'orchestrator', or 'OpenAI'.
    """
    def __init__(self, nats_url: str, runtime: PiRuntime):
        self.nats_url = nats_url
        self.runtime = runtime
        self.task_subject = "tasks.CODER"
        self.response_subject = "kernel.responses"
        self.consumer_name = "coder-agent-worker-v2"
        self.worker_id = str(uuid.uuid4())[:8]
        logger.info(f"Worker initialized with ID: {self.worker_id}")

    def build_prompts(self, payload: Dict[str, Any]) -> Tuple[str, str]:
        system_prompt = (
            "You are the CODER worker of the Firma kernel.\n"
            "CRITICAL: You MUST respond ONLY with a valid JSON object.\n"
            "Do not include any markdown formatting (like ```json), no explanations, and no preamble.\n"
            "Format: { \"event\": \"CODE_SUBMITTED\", \"artifacts\": { \"files\": [ { \"path\": \"file.py\", \"content\": \"...\", \"action\": \"CREATE\" } ] }, \"logs\": \"...\" }\n"
            "- 'artifacts' MUST be a dictionary containing a 'files' key. The 'files' key MUST be a list of objects: { \"path\": str, \"content\": str, \"action\": \"CREATE\" | \"UPDATE\" | \"DELETE\" }.\n"
            "- Do not speculate about state revisions or workflow phases."
        )
        
        context = {
            "task_id": payload.get("task_id"),
            "description": payload.get("description"),
            "acceptance_criteria": payload.get("acceptance_criteria"),
            "current_revision": payload.get("state_revision"),
            "existing_artifacts": payload.get("existing_artifacts", []),
        }
        user_prompt = (
            f"Implement the following task:\n{json.dumps(context, indent=2)}\n\n"
            "Reminder: Return ONLY a JSON object. No markdown. No text."
        )
        
        return system_prompt, user_prompt

    def validate_llm_output(self, raw_output: str) -> Dict[str, Any]:
        # 1. Clean markdown code blocks if present
        cleaned = raw_output.strip()
        if cleaned.startswith("```"):
            # Remove opening block
            cleaned = cleaned.split("\n", 1)[-1] if cleaned.startswith("```") else cleaned
            # Remove closing block
            if "```" in cleaned:
                cleaned = cleaned.rsplit("```", 1)[0]
        
        cleaned = cleaned.strip()
        
        try:
            data = json.loads(cleaned)
            logger.info(f"PARSED JSON DATA: {json.dumps(data, indent=2)}")
        except json.JSONDecodeError as e:
            logger.error(f"JSON Parsing failed for raw output: {raw_output}")
            raise ValueError(f"LLM output is not valid JSON: {str(e)}")

        if not isinstance(data, dict):
            raise ValueError("LLM output is not a JSON object")

        if data.get("event") != "CODE_SUBMITTED":
            raise ValueError(f"LLM attempted illegal event: {data.get('event')}")
        
        if "artifacts" not in data:
            logger.warning(f"LLM output missing 'artifacts' field. Keys found: {list(data.keys())}")
            raise ValueError("LLM output missing 'artifacts' field")
        
        # Normalize artifacts to the list format expected by the Kernel
        artifacts = data["artifacts"]
        logger.info(f"EXTRACTED ARTIFACTS (PRE-NORM): {json.dumps(artifacts, indent=2)}")
        
        if isinstance(artifacts, dict) and "files" not in artifacts:
            # Convert { "file.py": "content" } -> { "files": [ { "path": "file.py", "content": "content", "action": "CREATE" } ] }
            normalized_files = []
            for path, content in artifacts.items():
                normalized_files.append({
                    "path": path,
                    "content": content,
                    "action": "CREATE"
                })
            data["artifacts"] = {"files": normalized_files}
        
        logger.info(f"FINAL NORMALIZED ARTIFACTS: {json.dumps(data['artifacts'], indent=2)}")
        return data

    async def _submit_response(self, nc, payload_data: Dict[str, Any]):
        """Helper to wrap response in NATS envelope and publish via Core NATS."""
        envelope_data = {
            "protocol_version": "1.0",
            "message_type": "WORKER_RESPONSE",
            "message_id": payload_data["message_id"],
            "role": "CODER",
            "payload": payload_data,
            "timestamp": payload_data["timestamp"],
        }
        await nc.publish(
            self.response_subject,
            json.dumps(envelope_data).encode(),
        )

    async def _report_failure(self, nc, task_id: str, revision: int, reason: str):
        """Sends a TASK_FAILED event to the kernel before exiting."""
        logger.error(f"Reporting fatal failure for task {task_id}: {reason}")
        payload_data = {
            "protocol_version": "1.0",
            "message_id": str(uuid.uuid4()),
            "task_id": task_id,
            "state_revision": revision,
            "event": "TASK_FAILED",
            "sender_role": "CODER",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "artifacts": {},
            "logs": reason,
        }
        await self._submit_response(nc, payload_data)

    async def run(self):
        nc = None
        try:
            nc = NATS()
            await nc.connect(self.nats_url)
            js = nc.jetstream()
            
            logger.info(f"Pi-Agent connected to NATS. Listening on {self.task_subject}...")
            
            sub = await js.pull_subscribe(
                subject=self.task_subject,
                durable=self.consumer_name,
            )

            while True:
                try:
                    msgs = await sub.fetch(1, timeout=1.0)
                    for msg in msgs:
                        envelope = json.loads(msg.data.decode())
                        payload = envelope["payload"]
                        task_id = payload.get("task_id")
                        revision = payload.get("state_revision")
                        
                        logger.info(f"Processing task {task_id} (Rev {revision})")
                        
                        try:
                            sys_p, user_p = self.build_prompts(payload)
                            # Use the black-box runtime
                            raw_output = await self.runtime.llm.generate(sys_p, user_p)
                            result = self.validate_llm_output(raw_output)
                            
                            payload_data = {
                                "protocol_version": "1.0",
                                "message_id": str(uuid.uuid4()),
                                "task_id": task_id,
                                "state_revision": revision,
                                "event": result["event"],
                                "sender_role": "CODER",
                                "worker_id": self.worker_id,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                                "artifacts": result["artifacts"],
                                "logs": result.get("logs", ""),
                            }
                            
                            logger.info(f"Submitting payload for {task_id}: {json.dumps(payload_data)}")
                            await self._submit_response(nc, payload_data)
                            await msg.ack()
                            logger.info(f"Response submitted for {task_id}")

                            
                        except Exception as inner_e:
                            # These are task-specific errors, we report them and move to next message
                            logger.error(f"Task-level error for {task_id}: {inner_e}")
                            await self._report_failure(nc, task_id, revision, str(inner_e))
                            await msg.ack()

                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    # These are runtime-level errors. Report and DIE.
                    logger.critical(f"FATAL Runtime Error: {e}")
                    # We can't easily get the current task_id here, but we'll try to report if possible
                    # since this is a loop-level crash.
                    raise e
                    
        except Exception as e:
            logger.exception(f"Agent failed fatally: {e}")
            # If we had a connection, we'd try to report a general failure, 
            # but typically a crash is detected by the Kernel Watchdog.
            sys.exit(1)
        finally:
            if nc:
                await nc.close()

async def main():
    use_real_llm = os.getenv("USE_REAL_LLM", "false").lower() == "true"
    
    if use_real_llm:
        # Defaulting to a common NVIDIA NIM model since we have an nvapi key
        runtime = PiRuntime(model="nvidia/meta/llama-3.1-8b-instruct")
    else:
        # Mock Runtime for local testing
        class MockLLM(LLMProvider):
            async def generate(self, s, u):
                return json.dumps({"event": "CODE_SUBMITTED", "artifacts": {"files": [{"path": "main.py", "content": "print('MOCK')", "action": "CREATE"}]}})
        
        class MockRuntime(PiRuntime):
            def __init__(self):
                self.llm = MockLLM()
        
        runtime = MockRuntime()
        
    agent = CoderAgent(nats_url="nats://localhost:4222", runtime=runtime)
    await agent.run()

if __name__ == "__main__":
    asyncio.run(main())
