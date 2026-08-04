#!/usr/bin/env python3
"""Cleanup script for Firma project.

Modes:
  python tools/cleanup_project.py            # dry-run (default)
  python tools/cleanup_project.py --apply    # actually delete
  python tools/cleanup_project.py --apply --keep-venv  # keep .venv
"""
import argparse
import os
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


CATEGORIES = {
    "safe_to_delete": [
        # temp scripts
        REPO / "tmp_check_tokens.py",
        REPO / "tmp_check_tokens2.py",
        REPO / "tmp_live_test.py",
        REPO / "tmp_test_run.py",
        # windows junk / pid / backup
        REPO / "nul",
        REPO / "run_pi_mesh.py.bak",
        REPO / "run_pi_mesh.pid",
        # logs (root-level, ignored by git)
        REPO / "pimesh_live_run.log",
        REPO / "run.log",
        REPO / "run_pi_mesh_output.log",
        REPO / "run_pi_mesh_step2.log",
        REPO / "run_pi_mesh_step3.log",
        REPO / "test_run_watcher.log",
        # temp test dirs
        REPO / "tmp_audit_test",
        REPO / "test-project",
        # cache / tooling
        REPO / ".pytest_cache",
        REPO / ".qodo",
        # archive temp/legacy
        REPO / "archive" / "temp",
        REPO / "archive" / "legacy_scripts",
        REPO / "archive" / "sandbox_legacy",
    ],
    "ask_before_delete": [
        # potentially outdated dirs/files
        REPO / "firma_sandbox",
        REPO / "pi_workers",
        REPO / "artifact_store",
        REPO / "benchmarks",
        REPO / "Projects",
        REPO / "runs",
        REPO / "deliverable",
        REPO / "platform",
    ],
    "do_not_delete_automatically": [
        # local runtime / data (user decision required)
        REPO / ".venv",
        REPO / "firma.db",
        REPO / "firma.db-shm",
        REPO / "firma.db-wal",
        REPO / "data" / "db",
        REPO / "pimesh",
        REPO / ".crew",
        REPO / ".pi",
        REPO / "workspace",
    ],
}


def exists(item: Path) -> bool:
    return item.exists()


def remove(item: Path) -> None:
    if item.is_dir():
        shutil.rmtree(item)
    else:
        item.unlink()


def format_size(item: Path) -> str:
    try:
        if item.is_dir():
            total = 0
            for dirpath, dirnames, filenames in os.walk(item):
                for f in filenames:
                    fp = Path(dirpath) / f
                    try:
                        total += fp.stat().st_size
                    except FileNotFoundError:
                        pass
            return f"~{total / 1024:.1f} KB"
        else:
            return f"{item.stat().st_size / 1024:.1f} KB"
    except FileNotFoundError:
        return "?"


def main() -> int:
    parser = argparse.ArgumentParser(description="Firma project cleanup")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete files. Without this, it is a dry-run.",
    )
    parser.add_argument(
        "--keep-venv",
        action="store_true",
        help="Keep .venv even if it would otherwise be removed.",
    )
    args = parser.parse_args()

    if args.apply:
        print("=== APPLY MODE ===\n")
    else:
        print("=== DRY-RUN MODE === (use --apply to delete)\n")

    # collect targets
    safe_targets: list[Path] = []
    ask_targets: list[Path] = []
    protected = []

    for item in CATEGORIES["safe_to_delete"]:
        if exists(item):
            safe_targets.append(item)

    for item in CATEGORIES["ask_before_delete"]:
        if exists(item):
            ask_targets.append(item)

    for item in CATEGORIES["do_not_delete_automatically"]:
        if exists(item):
            protected.append(item)

    # print summary
    print("SAFE TO DELETE:")
    if not safe_targets:
        print("  (none)")
    for item in safe_targets:
        print(f"  - {item.relative_to(REPO)} ({format_size(item)})")

    print("\nASK BEFORE DELETE:")
    if not ask_targets:
        print("  (none)")
    for item in ask_targets:
        print(f"  - {item.relative_to(REPO)} ({format_size(item)})")

    print("\nPROTECTED / MANUAL REVIEW:")
    if not protected:
        print("  (none)")
    for item in protected:
        if item == REPO / ".venv" and args.keep_venv:
            continue
        print(f"  - {item.relative_to(REPO)} ({format_size(item)})")

    if not args.apply:
        print("\nNo files deleted. Re-run with --apply to delete safe + confirmed targets.")
        return 0

    # apply safe deletions
    deleted = 0
    for item in safe_targets:
        try:
            remove(item)
            print(f"DELETED (safe): {item.relative_to(REPO)}")
            deleted += 1
        except Exception as e:
            print(f"ERROR deleting {item}: {e}")

    # ask for ask-targets
    if ask_targets:
        answer = input("\nDelete the 'ask before delete' items above? [y/N]: ").strip().lower()
        if answer == "y":
            for item in ask_targets:
                try:
                    remove(item)
                    print(f"DELETED (ask): {item.relative_to(REPO)}")
                    deleted += 1
                except Exception as e:
                    print(f"ERROR deleting {item}: {e}")
        else:
            print("Skipped ask-targets.")

    print(f"\nDone. Deleted {deleted} items.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
