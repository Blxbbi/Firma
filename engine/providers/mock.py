import json
from enum import Enum
from engine.providers.base import LLMProvider

class MockMode(str, Enum):
    HAPPY = "HAPPY"
    INVALID_JSON = "INVALID_JSON"
    INVALID_SCHEMA = "INVALID_SCHEMA"

class MockLLMProvider:
    """
    A provider that returns predefined patterns to test the robustness of the LLMWorker.
    """
    def __init__(self, mode: MockMode):
        self.mode = mode

    def generate(self, prompt: str) -> str:
        prompt_lower = prompt.lower()
        
        # --- PLANNER RESPONSES ---
        if "plan" in prompt_lower:
            if self.mode == MockMode.HAPPY:
                return json.dumps({
                    "plan_name": "Add Two Numbers Plan",
                    "tasks": [
                        {
                            "id": "task-1",
                            "description": "Create a CLI script that adds two numbers",
                            "dependencies": [],
                            "expected_artifacts": [{"path": "main.py", "type": "CREATE"}],
                            "acceptance_criteria": ["EXISTS:main.py", "CMD:python main.py 2 3:5"]
                        }
                    ]
                })
            elif self.mode == MockMode.INVALID_JSON:
                return '{"plan_name": "Broken Plan", "tasks": ['
            elif self.mode == MockMode.INVALID_SCHEMA:
                return json.dumps({
                    "plan_name": "Invalid Plan",
                    "tasks": [
                        {
                            "id": "task-1",
                            "description": "Bad Task",
                            "dependencies": ["non-existent"],
                            "expected_artifacts": [],
                            "acceptance_criteria": []
                        }
                    ]
                })
            return "{}"

        # --- CODER RESPONSES ---
        if "add two numbers" in prompt_lower or "main.py" in prompt_lower:
            if self.mode == MockMode.HAPPY:
                return json.dumps({
                    "artifacts": [
                        {
                            "path": "main.py",
                            "content": "import sys\nif len(sys.argv) == 3:\n    print(int(sys.argv[1]) + int(sys.argv[2]))\n",
                            "action": "CREATE"
                        }
                    ]
                })

        if self.mode == MockMode.HAPPY:
            return json.dumps({
                "artifacts": [
                    {
                        "path": "main.py",
                        "content": "print('Hello from LLM')",
                        "action": "CREATE"
                    }
                ]
            })
        elif self.mode == MockMode.INVALID_JSON:
            return '{"artifacts": [{"path": "broken.py", "content": "oops", "action": "CREATE"' 
        elif self.mode == MockMode.INVALID_SCHEMA:
            return json.dumps({
                "artifacts": [
                    {
                        "path": "../malicious.py",
                        "content": "print('hacked')",
                        "action": "CREATE"
                    }
                ]
            })
        
        return ""
