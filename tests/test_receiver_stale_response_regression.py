"""Regression: PiMeshReceiverLoop darf keine veraltete (andere run_id) Response
konsumieren/publishen -- und muss die echte Response (gleiche task_id, gleiche
state_revision, aber erwartete run_id) genau einmal publishen.

Reproduziert den P3-Stale-File-Bug: _consumed war nur ueber (task_id, state_revision)
geschluesselt, OHNE run_id. Eine im Crew-cwd liegengebliebene
worker_response.task-N.response.json aus einem Vorgaenger-Run (fremde run_id)
vergiftete das Dedup -> die echte Antwort dies Runs (identischer Key) wurde als
Duplikat stillschweigend gedroppt -> HARD TIMEOUT.

Lauf: python tests/test_receiver_stale_response_regression.py
"""
import json
import os
import sys
import tempfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from run_pi_mesh import PiMeshReceiverLoop


def _write_response(worker_dir, task_id, run_id, rev, event="CODE_SUBMITTED", role="CODER"):
    path = os.path.join(worker_dir, f"worker_response.{task_id}.response.json")
    payload = {
        "protocol_version": "1.0",
        "message_id": f"{task_id}-{run_id}-{rev}",
        "task_id": task_id,
        "run_id": run_id,
        "state_revision": rev,
        "event": event,
        "sender_role": role,
        "artifacts": [],
        "timestamp": "2026-07-19T00:00:00+00:00",
        "logs": "regression",
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    return path


def _make_receiver(root, expected_run_id):
    # transport wird in scan_once nicht genutzt -> Mock reicht.
    transport = mock.MagicMock()
    crew_cwds = {"CODER": "crew"}
    return PiMeshReceiverLoop(
        transport=transport,
        crew_cwds=crew_cwds,
        project_root=root,
        expected_run_id=expected_run_id,
        interval=1.0,
    )


def _worker_dir(root):
    d = os.path.join(root, "crew", ".pi", "messenger", "crew")
    os.makedirs(d, exist_ok=True)
    return d


def test_receiver_skips_stale_other_run_response():
    """Kern-Regression: stale File mit FREMDER run_id (gleiche task_id/rev) wird
    ignoriert; echte Response (erwartete run_id) wird genau einmal published.
    Faengt den originalen Bug (ohne run_id im Dedup-Key)."""
    with tempfile.TemporaryDirectory() as root:
        wd = _worker_dir(root)
        OLD, NEW = "old-run-0000", "new-run-1111"
        task_id = "task-1"
        _write_response(wd, task_id, run_id=OLD, rev=1)  # stale aus Vorgaenger-Run

        rx = _make_receiver(root, expected_run_id=NEW)

        # 1) Scan mit NUR der stale (fremden) Response -> muss uebersprungen werden.
        out1 = rx.scan_once()
        assert out1 == [], f"stale other-run response must be skipped, got {out1}"

        # 2) echter Task ueberschreibt dieselbe Datei mit erwarteter run_id.
        _write_response(wd, task_id, run_id=NEW, rev=1)

        # 3) Scan muss genau die echte (NEW_RUN) Response publishen.
        out2 = rx.scan_once()
        assert len(out2) == 1, f"expected exactly 1 published, got {out2}"
        p = out2[0]["payload"]
        assert p["run_id"] == NEW, p
        assert p["task_id"] == task_id, p
        assert out2[0]["correlation_id"] == task_id

        # 4) erneuter Scan darf nicht erneut publishen (Dedup).
        out3 = rx.scan_once()
        assert out3 == [], f"must not republish, got {out3}"


def test_receiver_consumed_key_includes_revision():
    """Zwei Responses gleiche task_id, unterschiedliche state_revision muessen
    beide (in Reihenfolge) konsumiert werden, nie die falsche.
    Schuetzt die revision-Dimension des Dedup-Keys (run_id, task_id, state_revision)."""
    with tempfile.TemporaryDirectory() as root:
        wd = _worker_dir(root)
        RUN = "run-rev-2222"
        task_id = "task-1"
        rx = _make_receiver(root, expected_run_id=RUN)

        _write_response(wd, task_id, run_id=RUN, rev=1)
        out1 = rx.scan_once()
        assert len(out1) == 1 and out1[0]["payload"]["state_revision"] == 1, out1

        _write_response(wd, task_id, run_id=RUN, rev=2)  # retry/claim mit hoeherer rev
        out2 = rx.scan_once()
        assert len(out2) == 1 and out2[0]["payload"]["state_revision"] == 2, out2

        out3 = rx.scan_once()
        assert out3 == [], f"must not republish, got {out3}"


if __name__ == "__main__":
    test_receiver_skips_stale_other_run_response()
    test_receiver_consumed_key_includes_revision()
    print("ALL TESTS PASSED")
