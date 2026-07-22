import asyncio
import json
import uuid
from datetime import datetime, timezone
from nats.aio.client import Client as NATS

async def run_worker():
    print("!!! WORKER STARTING !!!")
    try:
        nc = NATS()
        await nc.connect("nats://localhost:4222")
        print("!!! WORKER CONNECTED !!!")
        js = nc.jetstream()
        
        print("Worker subscribing...")
        sub = await js.pull_subscribe(
            subject="tasks.*",
            durable="generic-worker-group",
            stream="TASKS"
        )
        print("Worker subscribed!")
        
        while True:
            try:
                msgs = await sub.fetch(batch=1, timeout=1.0)
                for msg in msgs:
                    print(f"Worker fetched: {msg}")
                    data = json.loads(msg.data.decode())
                    print(f"Worker processing: {data['payload']['task_id']}")
                    await asyncio.sleep(1)
                    
                    # Simple response
                    resp = {
                        "protocol_version": "1.0",
                        "message_type": "WORKER_RESPONSE",
                        "message_id": str(uuid.uuid4()),
                        "correlation_id": data.get("correlation_id", "unknown"),
                        "sender_id": "pi-coder-01",
                        "role": "CODER",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "payload": {
                            "task_id": data["payload"]["task_id"],
                            "state_revision": data["payload"]["state_revision"],
                            "event": "CODE_SUBMITTED",
                            "artifacts": {"files": []}
                        }
                    }
                    await js.publish("kernel.responses", json.dumps(resp).encode())
                    await msg.ack()
                    print("Worker sent response and acked.")
            except Exception as e:
                if "TimeoutError" not in str(type(e)):
                    print(f"Worker error: {e}")
                await asyncio.sleep(0.1)
    except Exception as e:
        print(f"Critical Worker Error: {e}")

if __name__ == "__main__":
    print("Entry point reached")
    asyncio.run(run_worker())
