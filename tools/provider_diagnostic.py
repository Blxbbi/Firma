import asyncio
import os
import time
import logging
from typing import Optional

# Add current directory to path to import engine
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from engine.providers.openrouter_provider import OpenRouterProvider
from engine.exceptions import WorkerExecutionError

# Setup basic logging to see exactly what happens
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger("ProviderDiag")

async def test_connectivity(api_key: str, model: str = "meta-llama/llama-3.1-8b-instruct"):
    logger.info(f"--- Starting Diagnostic for Provider: OpenRouter ---")
    logger.info(f"Using Model: {model}")
    
    provider = OpenRouterProvider(api_key=api_key)
    
    # Test 1: Simple Text Generation
    logger.info("\n[Test 1] Simple Text Generation ('Say Hello')")
    try:
        start = time.perf_counter()
        # Using a very short timeout for the diagnostic to avoid hanging the script
        response = await provider.generate(
            system_prompt="You are a helpful assistant.", 
            user_prompt="Say 'Connectivity Successful' in 3 words.", 
            timeout=15
        )
        duration = time.perf_counter() - start
        logger.info(f"✅ SUCCESS: Received response: '{response}'")
        logger.info(f"⏱️ Latency: {duration:.2f}s")
    except WorkerExecutionError as e:
        logger.error(f"❌ FAILED: {e.error_code} | {str(e)}")
    except Exception as e:
        logger.exception(f"❌ UNEXPECTED ERROR: {str(e)}")

    # Test 2: Simple JSON Generation
    logger.info("\n[Test 2] Simple JSON Generation")
    schema = {"type": "object", "properties": {"status": {"type": "string"}}}
    try:
        start = time.perf_counter()
        response = await provider.generate_json(
            system_prompt="Return JSON only.", 
            user_prompt="Return a JSON object with status='ok'.", 
            schema=schema, 
            timeout=15
        )
        duration = time.perf_counter() - start
        logger.info(f"✅ SUCCESS: Received JSON: {response}")
        logger.info(f"⏱️ Latency: {duration:.2f}s")
    except WorkerExecutionError as e:
        logger.error(f"❌ FAILED: {e.error_code} | {str(e)}")
    except Exception as e:
        logger.exception(f"❌ UNEXPECTED ERROR: {str(e)}")

async def main():
    # Try to get key from environment first
    api_key = os.environ.get("OPENROUTER_API_KEY")
    
    if not api_key or api_key == "PLACEHOLDER_OPENROUTER_KEY":
        print("\n--- OpenRouter API Key not found in environment ---")
        api_key = input("Please enter your OpenRouter API Key: ").strip()
        if not api_key:
            print("No API Key provided. Exiting.")
            return

    await test_connectivity(api_key)

if __name__ == "__main__":
    asyncio.run(main())
