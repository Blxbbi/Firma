import logging
import json
import asyncio
import httpx
import time
from openai import OpenAI, APIStatusError
from typing import Any, Dict
from .base import BaseLLMProvider
from engine.exceptions import WorkerExecutionError

logger = logging.getLogger(__name__)

class OpenRouterProvider(BaseLLMProvider):
    """
    OpenRouter implementation of the LLM Provider.
    Uses OpenAI-compatible API with robust httpx client.
    """
    def __init__(self, api_key: str, model: str = "meta-llama/llama-3.1-8b-instruct:free"):
        # Explicit HTTP client with hard timeouts
        self.http_client = httpx.Client(
            timeout=httpx.Timeout(
                connect=10.0,
                read=30.0,
                write=30.0,
                pool=5.0,
            ),
            limits=httpx.Limits(
                max_connections=10,
                max_keepalive_connections=5,
            ),
        )
        
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
            http_client=self.http_client
        )
        self.model = model

    def _sync_generate(self, system_prompt: str, user_prompt: str, timeout: int) -> str:
        logger.info("[Provider] _sync_call START")
        start = time.monotonic()
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                timeout=timeout,
                extra_headers={
                    "HTTP-Referer": "https://firma-kernel.local", 
                    "X-Title": "Firma Deterministic Engine",
                }
            )
            duration = time.monotonic() - start
            logger.info(f"[Provider] _sync_call END in {duration:.2f}s")
            return response.choices[0].message.content
        except APIStatusError as e:
            duration = time.monotonic() - start
            logger.error(f"[Provider] HTTP Error {e.status_code} after {duration:.2f}s: {e.message}")
            # 4xx errors (except 429) are fatal
            if 400 <= e.status_code < 500 and e.status_code != 429:
                raise WorkerExecutionError(f"Provider Fatal Error: {e.message}", f"HTTP_{e.status_code}")
            raise e
        except Exception as e:
            duration = time.monotonic() - start
            logger.exception(f"[Provider] _sync_call ERROR after {duration:.2f}s: {str(e)}")
            raise e

    def _sync_generate_json(self, system_prompt: str, user_prompt: str, schema: Dict[str, Any], timeout: int) -> Dict[str, Any]:
        logger.info("[Provider] _sync_call START (JSON)")
        start = time.monotonic()
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": f"{system_prompt}\n\nReturn only valid JSON. Schema: {json.dumps(schema)}"},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                timeout=timeout,
                extra_headers={
                    "HTTP-Referer": "https://firma-kernel.local", 
                    "X-Title": "Firma Deterministic Engine",
                }
            )
            duration = time.monotonic() - start
            logger.info(f"[Provider] _sync_call END (JSON) in {duration:.2f}s")
            content = response.choices[0].message.content
            return json.loads(content)
        except APIStatusError as e:
            duration = time.monotonic() - start
            logger.error(f"[Provider] HTTP Error {e.status_code} after {duration:.2f}s (JSON): {e.message}")
            if 400 <= e.status_code < 500 and e.status_code != 429:
                raise WorkerExecutionError(f"Provider Fatal Error: {e.message}", f"HTTP_{e.status_code}")
            raise e
        except Exception as e:
            duration = time.monotonic() - start
            logger.exception(f"[Provider] _sync_call ERROR (JSON) after {duration:.2f}s: {str(e)}")
            raise e

    async def _generate(self, system_prompt: str, user_prompt: str, timeout: int = 120) -> str:
        logger.info("[Provider] ENTER wait_for")
        try:
            return await asyncio.to_thread(self._sync_generate, system_prompt, user_prompt, timeout)
        except Exception as e:
            logger.error(f"OpenRouter _generate failed: {str(e)}")
            raise e

    async def _generate_json(self, system_prompt: str, user_prompt: str, schema: Dict[str, Any], timeout: int = 120) -> Dict[str, Any]:
        logger.info("[Provider] ENTER wait_for (JSON)")
        try:
            return await asyncio.to_thread(self._sync_generate_json, system_prompt, user_prompt, schema, timeout)
        except Exception as e:
            logger.error(f"OpenRouter _generate_json failed: {str(e)}")
            raise e
