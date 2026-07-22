import asyncio
import os
import sys
import logging
import json
from datetime import datetime
from typing import Dict, Any, Optional

# Ensure the root directory is in the python path
sys.path.append(os.getcwd())

from engine.providers.nvidia_provider import NvidiaProvider
from workers.planner import PlannerWorker
from workers.executor import ExecutionWorker
from engine.models import Message

# Setup minimal logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("SMOKE_TEST")

async def run_smoke_test():
    # 1. Setup
    api_key = "REDACTED_NVIDIA_KEY"
    provider = NvidiaProvider(api_key=api_key)
    
    planner = PlannerWorker(provider=provider, model_name="meta/llama-3.1-8b-instruct")
    executor = ExecutionWorker(provider=provider, model_name="meta/llama-3.1-70b-instruct")
    
    logger.info("🚀 Starting Cognitive Smoke Test...")
    
    # --- TEST 1: Planner Worker ---
    logger.info("\n--- [TEST 1] Planner Worker: Hello World ---")
    try:
        planner_res = await planner.handle_request(
            project_id="smoke-test-proj",
            user_prompt="Create a simple hello world text file.",
            task_id="smoke-task-1"
        )
        logger.info(f"✅ Planner responded successfully.")
        logger.info(f"Payload: {json.dumps(planner_res.payload, indent=2)}")
    except Exception as e:
        logger.error(f"❌ Planner failed: {e}")
        return

    # --- TEST 2: Executor Worker ---
    logger.info("\n--- [TEST 2] Executor Worker: Hello World ---")
    try:
        # We simulate a task definition that a planner would have produced
        dummy_task_def = {
            "description": "Create a file named hello.txt with content 'Hello from Firma!'",
            "expected_artifacts": [{"path": "hello.txt", "type": "CREATE"}],
            "acceptance_criteria": ["hello.txt exists", "contains 'Hello from Firma!'"]
        }
        
        executor_res = await executor.handle_assignment(
            project_id="smoke-test-proj",
            plan_id="smoke-plan-1",
            task_id="smoke-task-2",
            task_definition=dummy_task_def
        )
        logger.info(f"✅ Executor responded successfully.")
        logger.info(f"Payload: {json.dumps(executor_res.payload, indent=2)}")
    except Exception as e:
        logger.error(f"❌ Executor failed: {e}")
        return

    logger.info("\n✨ ALL COGNITIVE TESTS PASSED! The Pipeline is Healthy. ✨")

if __name__ == "__main__":
    asyncio.run(run_smoke_test())
