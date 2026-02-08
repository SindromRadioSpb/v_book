#!/usr/bin/env python3
"""Cleanup WAL files and checkpoint database."""

import sqlite3
from pathlib import Path
import sys

db_path = Path(r"M:\V_book\HDLE_Processing\hewiki_gpu_processing.db")

print(f"Connecting to: {db_path}")
print(f"Size: {db_path.stat().st_size / 1024**3:.2f} GB")

# Connect and checkpoint
try:
    conn = sqlite3.connect(db_path)

    # Checkpoint WAL to main database
    print("Checkpointing WAL...")
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    # Close connection
    conn.close()
    print("✅ WAL checkpoint complete")

    # Check files
    wal_path = Path(str(db_path) + "-wal")
    shm_path = Path(str(db_path) + "-shm")

    if wal_path.exists():
        print(f"⚠️  WAL still exists: {wal_path.stat().st_size / 1024:.1f} KB")
    else:
        print("✅ WAL removed")

    if shm_path.exists():
        print(f"⚠️  SHM still exists: {shm_path.stat().st_size / 1024:.1f} KB")
    else:
        print("✅ SHM removed")

except Exception as e:
    print(f"❌ Error: {e}")
    sys.exit(1)
