
import sqlite3
from datetime import datetime

DB_PATH = "data/db/snake_validation.db"

def inspect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    print("--- RUNS TABLE ---")
    cursor.execute("SELECT id, status FROM runs")
    runs = cursor.fetchall()
    for run in runs:
        print(f"ID: {run['id']} | Status: {run['status']}")

    if not runs:
        print("No runs found.")
        return

    # Use the latest run
    run_id = runs[0]['id']
    print(f"\n--- DETAILED INSPECTION FOR RUN: {run_id} ---")

    print("\n--- TASKS TABLE ---")
    cursor.execute("""
        SELECT id, state, execution_phase, assigned_worker, 
               assigned_role, retry_count, lease_expires_at, updated_at 
        FROM tasks 
        WHERE run_id = ?
    """, (run_id,))
    tasks = cursor.fetchall()
    for t in tasks:
        print(f"Task: {t['id']}")
        print(f"  State: {t['state']}")
        print(f"  Phase: {t['execution_phase']}")
        print(f"  Worker: {t['assigned_worker']}")
        print(f"  Role: {t['assigned_role']}")
        print(f"  Retry Count: {t['retry_count']}")
        print(f"  Lease: {t['lease_expires_at']}")
        print(f"  Updated: {t['updated_at']}")
        print("-" * 30)

    conn.close()

if __name__ == "__main__":
    inspect()
