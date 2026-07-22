import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from engine.exceptions import WorkerExecutionError

logger = logging.getLogger(__name__)

class BaseLLMProvider(ABC):
    """
    Base interface for LLM providers. 
    Treated as a pure IO device: Text in, Text out.
    No database access, no session, no state.
    """

    async def generate(self, system_prompt: str, user_prompt: str, timeout: int = 300) -> str:
        """
        Robust wrapper for text generation with timeout and latency tracking.
        """
        logger.debug(f"[Provider] Generating text using {self.__class__.__name__} (timeout={timeout}s)")
        start_time = time.monotonic()
        try:
            result = await asyncio.wait_for(
                self._generate(system_prompt, user_prompt, timeout),
                timeout=timeout + 5 # Give the provider a small buffer over its own timeout
            )
            duration = time.monotonic() - start_time
            logger.debug(f"[Provider] Text generation successful: {self.__class__.__name__} in {duration:.2f}s")
            return result
        except asyncio.TimeoutError:
            duration = time.monotonic() - start_time
            logger.error(f"[Provider] TIMEOUT: {self.__class__.__name__} exceeded {duration:.2f}s")
            raise WorkerExecutionError(f"LLM provider {self.__class__.__name__} timed out", "LLM_TIMEOUT")
        except Exception as e:
            duration = time.monotonic() - start_time
            logger.exception(f"[Provider] ERROR: {self.__class__.__name__} failed after {duration:.2f}s: {str(e)}")
            if isinstance(e, WorkerExecutionError):
                raise e
            raise WorkerExecutionError(f"LLM provider {self.__class__.__name__} error: {str(e)}", "LLM_ERROR")

    async def generate_json(self, system_prompt: str, user_prompt: str, schema: Dict[str, Any], timeout: int = 300) -> Dict[str, Any]:
        """
        Robust wrapper for JSON generation with timeout and latency tracking.
        """
        logger.debug(f"[Provider] Generating JSON using {self.__class__.__name__} (timeout={timeout}s)")
        start_time = time.monotonic()
        try:
            result = await asyncio.wait_for(
                self._generate_json(system_prompt, user_prompt, schema, timeout),
                timeout=timeout + 5
            )
            duration = time.monotonic() - start_time
            logger.debug(f"[Provider] JSON generation successful: {self.__class__.__name__} in {duration:.2f}s")
            return result
        except asyncio.TimeoutError:
            duration = time.monotonic() - start_time
            logger.error(f"[Provider] TIMEOUT: {self.__class__.__name__} exceeded {duration:.2f}s during JSON gen")
            raise WorkerExecutionError(f"LLM provider {self.__class__.__name__} timed out during JSON generation", "LLM_TIMEOUT")
        except Exception as e:
            duration = time.monotonic() - start_time
            logger.exception(f"[Provider] ERROR: {self.__class__.__name__} failed after {duration:.2f}s during JSON gen: {str(e)}")
            if isinstance(e, WorkerExecutionError):
                raise e
            raise WorkerExecutionError(f"LLM provider {self.__class__.__name__} JSON error: {str(e)}", "LLM_ERROR")

    @abstractmethod
    async def _generate(self, system_prompt: str, user_prompt: str, timeout: int) -> str:
        """Internal implementation of text generation."""
        pass

    @abstractmethod
    async def _generate_json(self, system_prompt: str, user_prompt: str, schema: Dict[str, Any], timeout: int) -> Dict[str, Any]:
        """Internal implementation of JSON generation."""
        pass
