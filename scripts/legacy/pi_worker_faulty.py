import asyncio
import json
import uuid
import sys
import os
from datetime import datetime, timezone
from nats.aio.client import Client as NATS

async def run_worker(fault_type=None):
    """
    Phase 1C Faulty Worker.
    Faults:
    - crash_pre_publish: dies before js.publish
    - crash_post_publish: dies after js.publish, before msg.ack()
    """
    print(f"[{datetime.now().isoformat()}] Worker starting (Fault: {fault_type})...")
    
    nc = NATS()
    try:
        await nc.connect("nats://localhost:4222")
        js = nc.jetstream()
        
        subject = "tasks.CODER"
        sub = await js.pull_subscribe(
            subject=subject,
            durable="coder-crash-test",
            stream="TASKS"
        )
        print(f"[{datetime.now().isoformat()}] Subscribed to {subject}.")

        # Loop until a task is processed (to handle redeliveries and timing)
        while True:
            try:
                msgs = await sub.fetch(batch=1, timeout=1.0)
                if not msgs:
                    continue
                for msg in msgs:
                    print(f"[{datetime.now().isoformat()}] Fetched dispatch.")
                    data = json.loads(msg.data.decode())
                    payload = data["payload"]
                    
                    await asyncio.sleep(0.2)
                    
                    if fault_type == "crash_pre_publish":
                        print(f"[{datetime.now().isoformat()}] FAULT: Crashing pre-publish...")
                        os._exit(1)
                        
                    response_payload = {
                        "task_id": payload["task_id"],
                        "state_revision": payload["state_revision"],
                        "event": "CODE_SUBMITTED",
                        "artifacts": {"files": []},
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                    
                    envelope = {
                        "protocol_version": "1.0",
                        "message_type": "WORKER_RESPONSE",
                        "message_id": str(uuid.uuid4()),
                        "correlation_id": data.get("correlation_id", "unknown"),
                        "sender_id": "pi-coder-faulty",
                        "role": "CODER",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "payload": response_payload
                    }
                    
                    await js.publish("kernel.responses", json.dumps(envelope).encode())
                    print(f"[{datetime.now().isoformat()}] Published response.")
                    
                    if fault_type == "crash_post_publish":
                        print(f"[{datetime.now().isoformat()}] FAULT: Crashing post-publish...")
                        os._exit(1)
                        
                    await msg.ack()
                    print(f"[{datetime.now().isoformat()}] Acked dispatch.")
                    return
            except Exception as e:
                if "timeout" in str(e).lower():
                    continue
                print(f"[{datetime.now().isoformat()}] Loop error: {e}")
                break

    except Exception as e:
        print(f"[{datetime.now().isoformat()}] Error: {e}")
        sys.exit(1)
    finally:
        await nc.close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--fault", type=str, default=None)
    args = parser.parse_args()
    asyncio.run(run_worker(args.fault))
