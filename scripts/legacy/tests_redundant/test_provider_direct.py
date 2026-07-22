import asyncio
import json
import logging
from engine.providers.nvidia_provider import NvidiaProvider

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PROVIDER_TEST")

async def test_nvidia_provider():
    api_key = "REDACTED_NVIDIA_KEY"
    provider = NvidiaProvider(api_key=api_key)
    
    print("\n--- Testing Raw Generate ---")
    try:
        res = await provider.generate(
            system_prompt="You are a helpful assistant.",
            user_prompt="Hello! Are you working?"
        )
        print(f"Response: {res}")
    except Exception as e:
        print(f"Error in generate: {e}")

    print("\n--- Testing JSON Generate ---")
    schema = {
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "value": {"type": "integer"}
        },
        "required": ["status", "value"]
    }
    try:
        res_json = await provider.generate_json(
            system_prompt="Return a status and a random number.",
            user_prompt="Generate JSON",
            schema=schema
        )
        print(f"JSON Response: {json.dumps(res_json, indent=2)}")
    except Exception as e:
        print(f"Error in generate_json: {e}")

if __name__ == "__main__":
    asyncio.run(test_nvidia_provider())
