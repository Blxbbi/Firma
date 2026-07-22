import logging
import time
import json
import os
from typing import Any, Dict
from .base import BaseLLMProvider

logger = logging.getLogger(__name__)

class ManualProvider(BaseLLMProvider):
    """
    ManualProvider: A provider for testing that reads/writes to files.
    Allows a human (or another agent) to act as the LLM.
    """
    def __init__(self, input_file: str = "llm_input.txt", output_file: str = "llm_output.txt"):
        self.input_file = input_file
        self.output_file = output_file

    def _wait_for_response(self, timeout: int) -> str:
        start_time = time.time()
        while (time.time() - start_time) < timeout:
            if os.path.exists(self.output_file):
                with open(self.output_file, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        # Clear the output file for the next request
                        with open(self.output_file, "w", encoding="utf-8") as clear_f:
                            clear_f.write("")
                        return content
            time.sleep(0.5)
        raise TimeoutError(f"ManualProvider: No response in {self.output_file} within {timeout}s")

    def generate(self, system_prompt: str, user_prompt: str, timeout: int = 60) -> str:
        request = {
            "type": "text",
            "system_prompt": system_prompt,
            "user_prompt": user_prompt
        }
        with open(self.input_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(request, indent=2))
        
        return self._wait_for_response(timeout)

    def generate_json(self, system_prompt: str, user_prompt: str, schema: Dict[str, Any], timeout: int = 60) -> Dict[str, Any]:
        request = {
            "type": "json",
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "schema": schema
        }
        with open(self.input_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(request, indent=2))
        
        raw_response = self._wait_for_response(timeout)
        return json.loads(raw_response)
