import asyncio
import sqlite3
from pathlib import Path

async def check_schema():
    db_path = Path("data/db/snake_validation_v3.db")
    if not db_path.exists():
        print(f"DB file not found: {db_path}")
        return

    # Using standard sqlite3 for simple PRAGMA check
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("--- TABLE INFO: tasks ---")
    cursor.execute("PRAGMA table_info(tasks);")
    columns = cursor.fetchall()
    for col in columns:
        # col: (id, name, type, notnull, default_value, pk)
        print(f"Column: {col[1]} | Type: {col[2]} | NotNull: {col[3]} | Default: {col[4]}")
    
    conn.close()

if __name__ == "__main__":
    asyncio.run(check_schema())
