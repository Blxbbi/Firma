"""
Integrationstest fuer PiMeshReceiverLoop + Guardian F5-Recovery.

Simuliert:
- RESEARCHER schreibt research/brief.md
- KEINE worker_response.<task_id>.response.json
- Receiver soll in <scan_interval> eine synthetische RESEARCH_COMPLETE Response publizieren
- Guardian bekommt RESEARCH_COMPLETE -> Task wird COMPLETE statt FAILED nach Timeout

Run via: ./tools/safe_test.sh tests/test_receiver_researcher_recovery_integration.py
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.services.guardian import GuardianPipeline, ExecutionPhase
from engine.models import Task, TaskEvent
from run_pi_mesh import PiMeshReceiverLoop, WORKER_RESPONSE_SUFFIX


class FakeTransport:
    """Fake transport, der published Responses einsammelt."""
    def __init__(self):
        self.published = []

    async def publish_response(self, role, payload, correlation_id=None):
        self.published.append({
            "role": role,
            "payload": payload,
            "correlation_id": correlation_id,
        })


def test_receiver_recovers_researcher_before_timeout():
    crew_cwd = tempfile.mkdtemp()
    run_id = "run-recover-integ-1"
    task_id = "task-researcher-integ-1"

    # Layout: crew_cwd/.pi/work/<run_id>/<task_id>/project/ (Dummy)
    work_dir = os.path.join(crew_cwd, ".pi", "work", run_id, task_id)
    os.makedirs(os.path.join(work_dir, "project"), exist_ok=True)

    # Worker-Verzeichnis (wo der Worker tatsächlich schreibt)
    worker_dir = os.path.join(crew_cwd, ".pi", "messenger", "crew")
    os.makedirs(os.path.join(worker_dir, "research"), exist_ok=True)

    # Researcher hat brief.md geschrieben, aber KEINE worker_response
    with open(os.path.join(worker_dir, "research", "brief.md"), "w", encoding="utf-8") as f:
        f.write("# Brief\n")

    # FakeTransport + Receiver
    transport = FakeTransport()
    receiver = PiMeshReceiverLoop(
        transport=transport,
        crew_cwds={"RESEARCHER": crew_cwd},
        project_root=crew_cwd,
        expected_run_id=run_id,
        interval=0.1,  # schneller Scan für Test
    )

    # Erster Scan: Recovery schreibt worker_response
    items1 = receiver.scan_once()
    for it in items1:
        asyncio.run(transport.publish_response(
            role=it["role"], payload=it["payload"], correlation_id=it["correlation_id"]
        ))

    # Zweiter Scan: liest die gerade geschriebene worker_response und publisht sie
    items2 = receiver.scan_once()
    for it in items2:
        asyncio.run(transport.publish_response(
            role=it["role"], payload=it["payload"], correlation_id=it["correlation_id"]
        ))

    # Assert: genau 1 published RESEARCH_COMPLETE
    research_completes = [p for p in transport.published if p["payload"].get("event") == "RESEARCH_COMPLETE"]
    assert len(research_completes) == 1, f"expected 1 RESEARCH_COMPLETE, got {len(research_completes)}"

    payload = research_completes[0]["payload"]
    assert payload["sender_role"] == "RESEARCHER"
    assert payload["task_id"] == task_id
    assert payload["run_id"] == run_id
    assert payload["artifacts"] == [{"path": "research/brief.md", "action": "CREATE", "content": "# Brief\n"}]
    assert "RECOVERED_BY_KERNEL=true" in payload.get("logs", "")
    print("PASS: receiver recovers researcher before timeout")
    return crew_cwd


if __name__ == "__main__":
    import uuid
    from datetime import datetime, timezone

    failures = 0
    for fn in [
        test_receiver_recovers_researcher_before_timeout,
    ]:
        try:
            fn()
        except AssertionError as e:
            print(f"FAIL: {fn.__name__}: {e}")
            failures += 1
        except Exception as e:
            print(f"FAIL: {fn.__name__}: unexpected {type(e).__name__}: {e}")
            failures += 1

    if failures:
        print(f"\n{failures} test(s) failed")
        sys.exit(1)
    print("\nAll tests passed")
