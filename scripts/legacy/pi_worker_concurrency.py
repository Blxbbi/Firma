import asyncio
import json
import uuid
import sys
import os
import argparse
from datetime import datetime, timezone
from nats.aio.client import Client as NATS

async def run_worker(role="CODER", consumer_name=None, delay=0.2):
    """
    Flexible worker for concurrency testing.
    """
    worker_id = f"{role.lower()}-{uuid.uuid4().hex[:6]}"
    print(f"[{datetime.now().isoformat()}] Worker {worker_id} starting (Role: {role}, Consumer: {consumer_name})...")
    
    nc = NATS()
    try:
        await nc.connect("nats://localhost:4222")
        js = nc.jetstream()
        
        subject = f"tasks.{role}"
        
        # Pull Subscribe
        # If consumer_name is provided, it's shared (Isolation Test).
        # If not, it's unique per worker (Race Test).
        durable = consumer_name if consumer_name else f"worker-{uuid.uuid4().hex[:8]}"
        
        sub = await js.pull_subscribe(
            subject=subject,
            durable=durable,
            stream="TASKS"
        )
        print(f"[{datetime.now().isoformat()}] Worker {worker_id} subscribed as {durable}.")

        # Try to fetch for a while
        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < 15:
            try:
                msgs = await sub.fetch(batch=1, timeout=1.0)
                if not msgs:
                    continue
                for msg in msgs:
                    print(f"[{datetime.now().isoformat()}] Worker {worker_id} fetched dispatch.")
                    data = json.loads(msg.data.decode())
                    payload = data["payload"]
                    
                    # Simulating processing time
                    await asyncio.sleep(delay)
                    
                    response_payload = {
                        "task_id": payload["task_id"],
                        "state_revision": payload["state_revision"],
                        "event": "CODE_SUBMITTED" if role == "CODER" else "VERIFY_SUCCESS",
                        "artifacts": {"files": []} if role == "CODER" else None,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                    
                    envelope = {
                        "protocol_version": "1.0",
                        "message_type": "WORKER_RESPONSE",
                        "message_id": str(uuid.uuid4()),
                        "correlation_id": data.get("correlation_id", "unknown"),
                        "sender_id": worker_id,
                        "role": role,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "payload": response_payload
                    }
                    
                    await js.publish("kernel.responses", json.dumps(envelope).encode())
                    print(f"[{datetime.now().isoformat()}] Worker {worker_id} published response.")
                    
                    await msg.ack()
                    print(f"[{datetime.now().isoformat()}] Worker {worker_id} acked dispatch.")
                    return
            except Exception as e:
                if "timeout" in str(e).lower():
                    continue
                print(f"[{datetime.now().isoformat()}] Worker {worker_id} error: {e}")
                break

        print(f"[{datetime.now().isoformat()}] Worker {worker_id} timed out waiting for task.")

    except Exception as e:
        print(f"[{datetime.now().isoformat()}] Worker {worker_id} critical error: {e}")
        sys.exit(1)
    finally:
        await nc.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", type=str, default="CODER")
    parser.add_argument("--consumer-name", type=str, default=None)
    parser.add_argument("--delay", type=float, default=0.2)
    args = parser.parse_args()
    asyncio.run(run_worker(args.role, args.consumer_name, args.delay))
