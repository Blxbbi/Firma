import asyncio
from nats.aio.client import Client as NATS

async def test_conn():
    print("Connecting...")
    nc = await NATS().connect("nats://localhost:4222")
    print(f"Connected: {nc}")
    if nc:
        await nc.close()

asyncio.run(test_conn())
