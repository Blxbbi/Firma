"""
Phase 1 (Idee D) — RunArchiver unit tests.

Run via: ./tools/safe_test.sh tests/test_run_archive.py
"""
import asyncio
import os
import sys
import tarfile
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.services.run_archive import RunArchiver


class FakeController:
    def __init__(self, run_id, status="COMPLETED", started_at=None, failure_reason=None):
        self.run_id = run_id
        self._status = status
        self._started = started_at or "2026-07-19T12:00:00Z"
        self._failure = failure_reason

    async def get_run_status(self, run_id):
        return {
            "run_id": run_id,
            "status": self._status,
            "started_at": self._started,
            "failure_reason": self._failure,
        }

    async def get_run_summary(self, run_id):
        return {
            "started_at": self._started,
            "terminal_state": self._status,
            "task_summary": [
                {
                    "task_id": "task-1",
                    "role": "CODER",
                    "state": "DONE",
                    "execution_phase": "CODING",
                    "review": None,
                }
            ],
            "failure_reason": self._failure,
            "summary_counters": {
                "total": 1,
                "done": 1,
                "failed": 0,
                "review_feedback": 0,
            },
        }


def _write_run_dir(base: Path, name: str, num_files: int = 1) -> Path:
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    for i in range(num_files):
        (d / f"file{i}.txt").write_text(f"content {i}", encoding="utf-8")
    return d


def test_archive_written_on_run_terminal():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        archive_dir = tmp / "archive_runs"
        artifact_dir = tmp / "artifacts"
        artifact_dir.mkdir()
        # one real artifact for the run
        (artifact_dir / "RUN_X" / "task-1").mkdir(parents=True)
        (artifact_dir / "RUN_X" / "task-1" / "game.js").write_text(
            "console.log(1)", encoding="utf-8"
        )

        archiver = RunArchiver(
            archive_runs_dir=archive_dir,
            artifact_dir=artifact_dir,
            keep_last_n=20,
            keep_compressed_last_n=100,
        )
        controller = FakeController("RUN_X")

        manifest = asyncio.run(
            archiver.archive_run(
                "RUN_X", controller, {"app": "counter", "FIRMA_TRANSPORT": "pimesh"}
            )
        )

        run_dir = archive_dir / "RUN_X"
        assert (run_dir / "manifest.json").exists()
        assert (run_dir / "config_snapshot.json").exists()
        assert (run_dir / "artifact_manifest.json").exists()
        assert (run_dir / "db_snapshot.json").exists()

        assert manifest["terminal_state"] == "COMPLETED"
        assert manifest["app"] == "counter"
        assert manifest["transport"] == "pimesh"
        assert len(manifest["artifact_refs"]) == 1
        assert Path(manifest["artifact_refs"][0]["path"]).exists()
        assert manifest["config_snapshot"]["FIRMA_TRANSPORT"] == "pimesh"


def test_retention_deletes_old_archives_keep_last_n():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        archive_dir = tmp / "archive_runs"
        artifact_dir = tmp / "artifacts"
        archive_dir.mkdir()
        # 6 fake runs with strictly increasing mtime (run-1 oldest ... run-6 newest)
        for i in range(1, 7):
            d = _write_run_dir(archive_dir, f"run-{i}")
            ts = 1_000_000 + i * 100
            os.utime(d, (ts, ts))

        archiver = RunArchiver(
            archive_runs_dir=archive_dir,
            artifact_dir=artifact_dir,
            keep_last_n=3,
            keep_compressed_last_n=100,
        )
        archiver.enforce_retention()

        remaining_dirs = sorted(p.name for p in archive_dir.iterdir() if p.is_dir())
        targz = sorted(p.name for p in archive_dir.glob("*.tar.gz"))

        assert remaining_dirs == ["run-4", "run-5", "run-6"], remaining_dirs
        assert targz == ["run-1.tar.gz", "run-2.tar.gz", "run-3.tar.gz"], targz
        # compressed archives are valid tarballs
        for name in targz:
            with tarfile.open(archive_dir / name) as tar:
                assert tar.getmembers()


if __name__ == "__main__":
    test_archive_written_on_run_terminal()
    test_retention_deletes_old_archives_keep_last_n()
    print("OK")
