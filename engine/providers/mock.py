import json
import logging
from enum import Enum
from engine.providers.base import BaseLLMProvider

class MockMode(str, Enum):
    HAPPY = "HAPPY"
    INVALID_JSON = "INVALID_JSON"
    INVALID_SCHEMA = "INVALID_SCHEMA"

class MockLLMProvider(BaseLLMProvider):
    """
    A provider that returns predefined patterns to test the robustness of the LLMWorker.
    """
    def __init__(self, mode: MockMode):
        self.mode = mode
        self._current_role: str | None = None
        self._current_task_id: str | None = None
        self._current_task_definition: dict | None = None

    def set_role_context(self, role: str, task_id: str, task_definition: dict | None = None) -> None:
        self._current_role = role
        self._current_task_id = task_id
        self._current_task_definition = task_definition or {}

    def _clear_role_context(self) -> None:
        self._current_role = None
        self._current_task_id = None
        self._current_task_definition = None

    async def _generate(self, system_prompt: str, user_prompt: str, timeout: int) -> str:
        return self.generate(user_prompt)

    async def _generate_json(self, system_prompt: str, user_prompt: str, schema, timeout: int) -> dict:
        text = self.generate(user_prompt)
        try:
            import json as _json
            return _json.loads(text)
        except Exception:
            return {}

    def _role_response(self) -> str:
        role = (self._current_role or "UNKNOWN").upper()
        task_def = self._current_task_definition or {}
        mode = self.mode

        # --- RESEARCHER ---
        if role == "RESEARCHER":
            if mode == MockMode.HAPPY:
                return json.dumps({
                    "brief_markdown": "# Research Brief\n\n## Findings\n- Counter app needs index.html, style.css, app.js\n- Use vanilla JS, no frameworks\n",
                    "sources": [
                        {"url": "https://example.com", "title": "Example", "snippet": "Counter app best practices."}
                    ],
                    "confidence": 0.9,
                })
            return json.dumps({"brief_markdown": "", "sources": [], "confidence": 0.0})

        # --- PLANNER ---
        if role == "PLANNER":
            if mode == MockMode.HAPPY:
                return json.dumps({
                    "plan_name": "Counter App Plan",
                    "tasks": [
                        {
                            "id": "task-1",
                            "description": "Create the HTML structure for the counter app",
                            "dependencies": [],
                            "expected_artifacts": [{"path": "index.html", "type": "CREATE"}],
                            "acceptance_criteria": ["EXISTS:index.html", "CONTAINS:index.html:<button"]
                        },
                        {
                            "id": "task-2",
                            "description": "Create CSS styling for the counter app",
                            "dependencies": [],
                            "expected_artifacts": [{"path": "style.css", "type": "CREATE"}],
                            "acceptance_criteria": ["EXISTS:style.css"]
                        },
                        {
                            "id": "task-3",
                            "description": "Create JavaScript logic for the counter app",
                            "dependencies": [],
                            "expected_artifacts": [{"path": "app.js", "type": "CREATE"}],
                            "acceptance_criteria": ["EXISTS:app.js", "CONTAINS:app.js:addEventListener"]
                        }
                    ]
                })
            elif mode == MockMode.INVALID_JSON:
                return '{"plan_name": "Broken Plan", "tasks": ['
            elif mode == MockMode.INVALID_SCHEMA:
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

        # --- CODER / EXECUTOR ---
        if role == "CODER" or role == "EXECUTOR":
            raw_expected = task_def.get("expected_artifacts") or ["index.html", "style.css", "app.js"]
            expected = []
            for a in raw_expected:
                if isinstance(a, dict):
                    p = a.get("path") or a.get("id") or ""
                    if p:
                        expected.append(p)
                elif isinstance(a, str):
                    expected.append(a)
            if not expected:
                expected = ["index.html", "style.css", "app.js"]
            if mode == MockMode.HAPPY:
                files = []
                for path in expected:
                    if path == "index.html":
                        content = "<html><body><h1>Counter</h1><button id=\"inc\">Increment</button><span id=\"count\">0</span><script src=\"app.js\"></script></body></html>"
                    elif path == "style.css":
                        content = "body { font-family: sans-serif; text-align: center; }"
                    elif path == "app.js":
                        content = "let count = 0; document.getElementById('inc').addEventListener('click', () => { count++; document.getElementById('count').innerText = count; });"
                    else:
                        content = "// placeholder"
                    files.append({"path": path, "content": content, "action": "CREATE"})
                return json.dumps({"artifacts": {"files": files}})
            elif mode == MockMode.INVALID_JSON:
                return '{"artifacts": {"files": [{"path": "broken.py", "content": "oops", "action": "CREATE"}]}'
            elif mode == MockMode.INVALID_SCHEMA:
                return json.dumps({
                    "artifacts": {
                        "files": [
                            {
                                "path": "../malicious.py",
                                "content": "print('hacked')",
                                "action": "CREATE"
                            }
                        ]
                    }
                })
            return ""

        # --- REVIEWER ---
        if role == "REVIEWER":
            return json.dumps({
                "verdict": "approve",
                "feedback": "Mock reviewer approval.",
                "artifacts_to_promote": []
            })

        # Fallback: role unknown -> empty response (should not happen in tests)
        return ""

    def generate(self, prompt: str) -> str:
        import os as _os
        print(f"[MOCK] generate() called | file={_os.path.abspath(__file__)} | role={self._current_role} | task_id={self._current_task_id} | prompt[:120]={prompt[:120]!r}")
        response = self._role_response()
        print(f"[MOCK] role_response returned | len={len(response)} | preview={response[:120]!r}")
        self._clear_role_context()
        return response
