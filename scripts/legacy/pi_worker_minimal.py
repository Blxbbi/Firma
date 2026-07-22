import asyncio
import json
import uuid
import sys
from datetime import datetime, timezone
from nats.aio.client import Client as NATS

async def run_worker():
    """
    Phase 1B Minimal Worker.
    Rule: Process exactly one task and exit.
    Rule: Sequence: Fetch -> Publish Response -> Ack Dispatch.
    """
    print(f"[{datetime.now().isoformat()}] Worker starting...")
    
    nc = NATS()
    try:
        # Rule 1: No reconnect magic. Connection failure = Process death.
        await nc.connect("nats://localhost:4222")
        js = nc.jetstream()
        print(f"[{datetime.now().isoformat()}] Connected to NATS.")

        # Rule: Unique Durable name for Phase 1B to avoid interference
        subject = "tasks.CODER"
        sub = await js.pull_subscribe(
            subject=subject,
            durable="coder-phase1b",
            stream="TASKS"
        )
        print(f"[{datetime.now().isoformat()}] Subscribed to {subject} as coder-phase1b.")

        # Rule 3: Process only one task
        try:
            msgs = await sub.fetch(batch=1, timeout=10.0)
            for msg in msgs:
                print(f"[{datetime.now().isoformat()}] Fetched dispatch.")
                
                data = json.loads(msg.data.decode())
                payload = data["payload"]
                
                # Simulation of work
                await asyncio.sleep(0.5)
                
                # Build Response
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
                    "sender_id": "pi-coder-phase1b",
                    "role": "CODER",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "payload": response_payload
                }
                
                # Rule 2: PUBLISH first, then ACK
                await js.publish("kernel.responses", json.dumps(envelope).encode())
                print(f"[{datetime.now().isoformat()}] Published response.")
                
                await msg.ack()
                print(f"[{datetime.now().isoformat()}] Acked dispatch.")
                
                # Exit after one task
                return 

        except Exception as e:
            print(f"[{datetime.now().isoformat()}] Error during fetch/process: {e}")
            sys.exit(1)

    except Exception as e:
        print(f"[{datetime.now().isoformat()}] Critical Worker Error: {e}")
        sys.exit(1)
    finally:
        await nc.close()
        print(f"[{datetime.now().isoformat()}] Connection closed.")

if __name__ == "__main__":
    asyncio.run(run_worker())
