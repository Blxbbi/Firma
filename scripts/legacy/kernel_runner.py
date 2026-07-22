import asyncio
import sys
import os
import json
from datetime import datetime, timezone
from nats.aio.client import Client as NATS

from engine.db import DatabaseManager
from engine.transport.pimessenger import PiMessengerTransport
from engine.orchestrator import Orchestrator
from unittest.mock import MagicMock

async def run_kernel(fault_type=None):
    """
    Faulty Kernel Runner.
    Faults:
    - crash_post_poll: dies after poll, before ack
    - crash_post_cas: dies after Guardian process (CAS), before ack
    """
    print(f"[{datetime.now().isoformat()}] Kernel starting (Fault: {fault_type})...")
    
    db_manager = DatabaseManager("sqlite:///mesh_crash_test.db")
    transport = PiMessengerTransport(sender_id="kernel-01")
    await transport.connect()
    
    scheduler = MagicMock()
    scheduler.run_tick = MagicMock()
    scheduler.assign_unassigned_ready_tasks = MagicMock()
    
    orchestrator = Orchestrator(
        db_manager=db_manager,
        scheduler=scheduler,
        transport=transport,
        execution_service=MagicMock(),
        sandbox=MagicMock()
    )
    
    # We override tick to inject faults
    async def faulty_tick():
        # 1. Scheduler (mocked)
        # 2. Poll
        messages = await transport.poll()
        
        if fault_type == "crash_post_poll" and messages:
            print(f"[{datetime.now().isoformat()}] FAULT: Crashing post-poll...")
            os._exit(1)
            
        for msg in messages:
            try:
                with db_manager.session_scope() as session:
                    full_payload = msg.envelope["payload"].copy()
                    full_payload["message_id"] = msg.envelope.get("message_id")
                    full_payload["timestamp"] = msg.envelope.get("timestamp")
                    full_payload["protocol_version"] = msg.envelope.get("protocol_version", "1.0")
                    
                    from engine.services.guardian import GuardianPipeline
                    from engine.services.artifact_store import ArtifactStore
                    guardian = GuardianPipeline(ArtifactStore())
                    guardian.process_response(session, full_payload)
                    
            finally:
                if fault_type == "crash_post_cas":
                    print(f"[{datetime.now().isoformat()}] FAULT: Crashing post-CAS...")
                    os._exit(1)
                await msg.ack()

    await faulty_tick()
    await transport.close()
    print(f"[{datetime.now().isoformat()}] Kernel finished normally.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--fault", type=str, default=None)
    args = parser.parse_args()
    asyncio.run(run_kernel(args.fault))
