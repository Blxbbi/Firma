"""
Smoke test: Researcher -> Planner -> Coder -> Reviewer in-process pipeline.

Run via: python tests/test_researcher_pipeline_smoke.py

Goal:
  - Verify the ResearcherWorker can participate in a real orchestrated run.
  - Verify the plan_draft side-file recovery works.
  - Verify the run can reach a terminal state without crashing.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.db import DatabaseManager
from engine.controller import RunController
from engine.scheduler import Scheduler
from engine.transport.internal_transport import InternalTransport
from engine.services.execution import ExecutionService
from engine.services.sandbox import LocalPythonSandbox
from engine.services.verification_registry import VerificationRegistry
from engine.services.verifiers.web_verifier import WebStructuralVerifier
from engine.services.run_archive import RunArchiver
from workers.researcher import ResearcherWorker
from workers.planner import PlannerWorker
from workers.executor import ExecutionWorker
from engine.providers.base import BaseLLMProvider
from engine.models import Base


class _MockResearcherProvider(BaseLLMProvider):
    async def _generate(self, system_prompt: str, user_prompt: str, timeout: int) -> str:
        return "mock"

    async def _generate_json(self, system_prompt: str, user_prompt: str, schema, timeout: int):
        return {
            "brief_markdown": (
                "# Research Brief\n\n"
                "## Project Findings\n"
                "- file: README.md | line: 1 | evidence: Firma project root detected\n"
                "- file: docs/vision/PiMesh_Architektur.md | line: 1 | evidence: architecture documentation present\n\n"
                "## Recommendations for Planner\n"
                "- Split website into: index.html, style.css, app.js\n"
                "- Use dark theme based on docs/vision/*.md\n\n"
                "## Risks/Constraints\n"
                "- Must read docs from project root only\n"
            )
        }


class _MockPlannerProvider(BaseLLMProvider):
    async def _generate(self, system_prompt: str, user_prompt: str, timeout: int) -> str:
        return "mock"

    async def _generate_json(self, system_prompt: str, user_prompt: str, schema, timeout: int):
        return {
            "plan_name": "Firma Website Smoke Plan",
            "tasks": [
                {
                    "id": "task-1",
                    "description": "Create a simple Firma website",
                    "dependencies": [],
                    "expected_artifacts": [{"path": "index.html", "type": "CREATE"}],
                    "acceptance_criteria": ["EXISTS:index.html", "CONTAINS:index.html:Firma"],
                    "scope_files": ["index.html"],
                    "protected_files": [],
                    "edit_mode": "force_create",
                    "allow_delete": False,
                }
            ],
        }


class _MockCoderProvider(BaseLLMProvider):
    async def _generate(self, system_prompt: str, user_prompt: str, timeout: int) -> str:
        return "mock"

    async def _generate_json(self, system_prompt: str, user_prompt: str, schema, timeout: int):
        return {
            "artifacts": {
                "files": [
                    {
                        "path": "index.html",
                        "action": "CREATE",
                        "content": "<html><body><h1>Firma Website</h1></body></html>",
                    }
                ]
            }
        }


async def _run_pipeline_smoke():
    tmp = Path("data/tmp_researcher_pipeline_smoke")
    tmp.mkdir(parents=True, exist_ok=True)
    db_path = tmp / "researcher_pipeline.db"
    if db_path.exists():
        db_path.unlink()

    db_manager = DatabaseManager(f"sqlite+aiosqlite:///{db_path}")
    async with db_manager.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    VerificationRegistry.register("structural_web", WebStructuralVerifier)

    researcher = ResearcherWorker(provider=_MockResearcherProvider(), model_name="mock/researcher", dummy_mode=False)
    planner = PlannerWorker(provider=_MockPlannerProvider(), model_name="mock/planner", dummy_mode=False)
    executor = ExecutionWorker(provider=_MockCoderProvider(), model_name="mock/coder", dummy_mode=False)

    async def worker_harness(msg):
        role = msg.get("role")
        task_id = msg.get("task_id")
        prompt = msg.get("prompt", "")
        run_id = msg.get("run_id", "")
        print(f"[Harness] {role} task {task_id}")

        if role == "RESEARCHER":
            resp = await researcher.handle_request(
                project_id=run_id,
                user_prompt=prompt,
                task_id=task_id,
                run_id=run_id,
                project_root=str(Path(__file__).resolve().parent.parent),
            )
            resp.payload["state_revision"] = msg.get("state_revision")
            resp.payload["run_id"] = run_id
            await transport.publish_response(role=role, payload=resp.payload)
        elif role == "PLANNER":
            resp = await planner.handle_request(project_id=run_id, user_prompt=prompt, task_id=task_id)
            resp.payload["state_revision"] = msg.get("state_revision")
            resp.payload["run_id"] = run_id
            await transport.publish_response(role=role, payload=resp.payload)
        elif role == "CODER":
            resp = await executor.handle_assignment(
                project_id=run_id,
                plan_id="plan-1",
                task_id=task_id,
                task_definition=msg.get("task_definition", {}),
                global_goal=msg.get("prompt", ""),
            )
            payload = resp.payload if hasattr(resp, "payload") else resp
            if isinstance(payload, dict):
                payload["state_revision"] = msg.get("state_revision")
                payload["run_id"] = run_id
            await transport.publish_response(role=role, payload=payload)
        elif role == "REVIEWER":
            await transport.publish_response(
                role=role,
                payload={
                    "project_id": run_id,
                    "run_id": run_id,
                    "task_id": task_id,
                    "state_revision": msg.get("state_revision"),
                    "event": "REVIEW_APPROVED",
                    "sender_role": "REVIEWER",
                    "logs": "Smoke approved",
                },
            )
        else:
            print(f"[Harness] Unknown role {role}")

    transport = InternalTransport()

    def scheduler_factory(db, messenger_callback=None):
        return Scheduler(db, messenger_callback=messenger_callback)

    def transport_factory():
        return transport

    controller = RunController(
        db_manager=db_manager,
        scheduler_factory=scheduler_factory,
        transport_factory=transport_factory,
        execution_service=ExecutionService(db_manager),
        sandbox=LocalPythonSandbox(),
    )

    print("[Smoke] Creating run...")
    run_id = await controller.create_run({
        "project_name": "Researcher Pipeline Smoke",
        "plan_name": "Smoke Plan",
        "prompt": "Build a simple Firma website using project docs.",
        "expected_artifacts": ["index.html"],
        "acceptance_criteria": ["EXISTS:index.html", "CONTAINS:index.html:Firma"],
        "verification_type": "structural_web",
    })
    print(f"[Smoke] run_id={run_id}")

    await controller.start_run(run_id, messenger_callback=worker_harness)

    last_status = None
    for _ in range(200):
        status_info = await controller.get_run_status(run_id)
        status = status_info["status"]
        if status != last_status:
            print(f"[Smoke] Status: {status} | metrics={status_info['metrics']}")
            last_status = status
        if status in {"COMPLETED", "FAILED", "CANCELLED"}:
            break
        await asyncio.sleep(0.1)

    archiver = RunArchiver()
    try:
        await archiver.archive_run(run_id, controller, {})
    except Exception as exc:
        print(f"[Smoke] archive failed (non-fatal): {exc}")

    final = await controller.get_run_status(run_id)
    print(f"[Smoke] final status={final['status']}")
    return final["status"]


if __name__ == "__main__":
    status = asyncio.run(_run_pipeline_smoke())
    if status == "COMPLETED":
        print("OK")
    else:
        print(f"FAIL final status={status}")
        raise SystemExit(1)
