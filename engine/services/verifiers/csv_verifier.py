import logging
import tempfile
import os
from typing import Tuple, List, Dict, Any
from sqlalchemy.orm import Session
from engine.services.verification_registry import BaseVerifier
from engine.services.execution import normalize_output

logger = logging.getLogger(__name__)

class CSVVerifier(BaseVerifier):
    """
    Industrial verifier for CSV aggregation tasks.
    """
    async def verify(self, session: Session, task_id: str, project_id: str, plan_version: int, artifacts: List[Dict[str, Any]]) -> Tuple[bool, str]:
        # The standard CSV Acceptance Matrix
        test_cases = [
            {"name": "valid_basic", "csv": "name,value\nAlice,10\nBob,20\nAlice,5\n", "expected": "Alice,15.0\nBob,20.0\n"},
            {"name": "invalid_number", "csv": "name,value\nCharlie,invalid\n", "expected": ""},
            {"name": "missing_value", "csv": "name,value\nDave,\n", "expected": ""},
            {"name": "empty_line", "csv": "name,value\n\nAlice,3\n", "expected": "Alice,3.0\n"},
        ]

        failures = []
        # We need the sandbox to run the code
        from engine.services.sandbox import LocalPythonSandbox
        sandbox = LocalPythonSandbox()

        for case in test_cases:
            with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".csv") as tmp:
                tmp.write(case["csv"])
                tmp.flush()
                tmp_path = tmp.name

            try:
                res = await sandbox.run(files=artifacts, command=f"main.py {tmp_path}", timeout=10.0)
                norm_output = normalize_output(res.stdout)
                norm_expected = normalize_output(case["expected"])

                if res.exit_code != 0:
                    failures.append({"test_case": case["name"], "reason": "non_zero_exit", "stderr": res.stderr.strip()})
                elif norm_output != norm_expected:
                    failures.append({"test_case": case["name"], "reason": "output_mismatch", "expected": norm_expected, "actual": norm_output})
            except Exception as e:
                failures.append({"test_case": case["name"], "reason": "exception", "stderr": str(e)})
            finally:
                if os.path.exists(tmp_path): os.unlink(tmp_path)

        if failures:
            report = ["\n--- ACCEPTANCE MATRIX FAILURE REPORT ---"]
            for fail in failures:
                case = fail["test_case"]
                reason = fail["reason"]
                if reason == "non_zero_exit": report.append(f"Case [{case}]: CRASHED. Stderr: {fail.get('stderr', 'N/A')}")
                elif reason == "output_mismatch": report.append(f"Case [{case}]: OUTPUT MISMATCH. Expected {repr(fail.get('expected'))}, got {repr(fail.get('actual'))}")
                else: report.append(f"Case [{case}]: FAILED ({reason})")
            report.append("--- END OF REPORT ---")
            return False, "\n".join(report)

        return True, "All CSV acceptance criteria passed."
