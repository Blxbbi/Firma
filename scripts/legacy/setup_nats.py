import asyncio
from nats.aio.client import Client as NATS

async def setup():
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
    
    # Delete existing streams to start fresh
    try:
        await js.delete_stream("TASKS")
        await js.delete_stream("RESPONSES")
    except Exception:
        pass

    print("Creating TASKS stream...")
    await js.add_stream(
        name="TASKS",
        subjects=["tasks.*"],
        retention="workqueue",
        storage="file",
        num_replicas=1,
    )

    print("Creating RESPONSES stream...")
    await js.add_stream(
        name="RESPONSES",
        subjects=["kernel.responses"],
        retention="workqueue",
        storage="file",
        num_replicas=1,
    )

    print("Adding kernel-consumer (no filter for WorkQueue)...")
    await js.add_consumer(
        stream="RESPONSES",
        durable_name="kernel-consumer",
        ack_policy="explicit",
        ack_wait=30,
        max_deliver=10,
        # REMOVED filter_subject to comply with WorkQueue
    )
    
    print("NATS Setup Complete.")
    await nc.close()

asyncio.run(setup())
