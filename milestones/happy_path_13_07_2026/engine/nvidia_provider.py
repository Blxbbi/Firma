import logging
import json
import asyncio
import openai
from openai import OpenAI
from typing import Any, Dict
from .base import BaseLLMProvider

logger = logging.getLogger(__name__)

import logging
import json
import asyncio
import httpx
import time
from openai import OpenAI
from typing import Any, Dict
from .base import BaseLLMProvider

logger = logging.getLogger(__name__)

class NvidiaProvider(BaseLLMProvider):
    """
    NVIDIA NIM implementation of the LLM Provider.
    Uses OpenAI-compatible API with a robust httpx client to prevent network hangs.
    """
    def __init__(self, api_key: str, model: str = "meta/llama-3.1-70b-instruct"):
        # Explicit HTTP client with hard timeouts for every socket state
        self.http_client = httpx.Client(
            timeout=httpx.Timeout(
                connect=10.0,
                read=300.0,
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
            base_url="https://integrate.api.nvidia.com/v1",
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
                timeout=timeout
            )
            duration = time.monotonic() - start
            logger.info(f"[Provider] _sync_call END in {duration:.2f}s")
            return response.choices[0].message.content
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
                timeout=timeout
            )
            duration = time.monotonic() - start
            logger.info(f"[Provider] _sync_call END (JSON) in {duration:.2f}s")
            content = response.choices[0].message.content
            return json.loads(content)
        except Exception as e:
            duration = time.monotonic() - start
            logger.exception(f"[Provider] _sync_call ERROR (JSON) after {duration:.2f}s: {str(e)}")
            raise e

    async def _generate(self, system_prompt: str, user_prompt: str, timeout: int = 300) -> str:
        logger.info("[Provider] ENTER wait_for")
        try:
            # The BaseLLMProvider already wraps this in wait_for, 
            # but we use to_thread to offload the sync call.
            return await asyncio.to_thread(self._sync_generate, system_prompt, user_prompt, timeout)
        except Exception as e:
            logger.error(f"Nvidia _generate failed: {str(e)}")
            raise e

    async def _generate_json(self, system_prompt: str, user_prompt: str, schema: Dict[str, Any], timeout: int = 300) -> Dict[str, Any]:
        logger.info("[Provider] ENTER wait_for (JSON)")
        try:
            return await asyncio.to_thread(self._sync_generate_json, system_prompt, user_prompt, schema, timeout)
        except Exception as e:
            logger.error(f"Nvidia _generate_json failed: {str(e)}")
            raise e
