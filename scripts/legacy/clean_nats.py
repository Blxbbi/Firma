import asyncio
from nats.aio.client import Client as NATS

async def clean():
    nc = NATS()
    connected = False
    for i in range(5):
        try:
            await nc.connect("nats://localhost:4222")
            connected = True
            break
        except Exception as e:
            print(f"Connection attempt {i+1} failed: {e}")
            await asyncio.sleep(2)

    if not connected:
        print("Could not connect to NATS")
        return

    js = nc.jetstream()
    
    try:
        # List all consumers for TASKS stream
        consumers = await js.consumers("TASKS")
        for c in consumers:
            print(f"Deleting consumer {c}")
            await js.remove_consumer("TASKS", c)
        
        # List all consumers for RESPONSES stream
        consumers_resp = await js.consumers("RESPONSES")
        for c in consumers_resp:
            print(f"Deleting consumer {c}")
            await js.remove_consumer("RESPONSES", c)
            
    except Exception as e:
        print(f"Clean failed: {e}")
    finally:
        await nc.close()

asyncio.run(clean())
