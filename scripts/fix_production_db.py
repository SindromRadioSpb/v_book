"""Fix production database schema version mismatch.

Problem: Migration 013 columns exist but schema_version is stuck at 12.
Solution: Check columns and update schema_version to 13.
"""

import sys
import os
import sqlite3
from pathlib import Path


def main():
    # Get production DB path
    if sys.platform == "win32":
        app_dir = Path(os.environ.get("LOCALAPPDATA")) / "HDLE"
    else:
        print("This script is for Windows only")
        return 1

    db_path = app_dir / "hdle.db"

    if not db_path.exists():
        print(f"Production DB not found: {db_path}")
        return 1

    print(f"Production DB: {db_path}")

    # Connect
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Check schema version
    cursor.execute("SELECT value FROM schema_meta WHERE key='schema_version'")
    version = cursor.fetchone()[0]
    print(f"Current schema version: {version}")

    # Check if migration 013 columns exist
    cursor.execute("PRAGMA table_info(tm_entry)")
    columns = {row[1] for row in cursor.fetchall()}

    has_lemma_id = "lemma_id" in columns
    has_cluster_id = "cluster_id" in columns
    has_ngram_id = "ngram_id" in columns

    print(f"\nColumn status:")
    print(f"  lemma_id: {'EXISTS' if has_lemma_id else 'MISSING'}")
    print(f"  cluster_id: {'EXISTS' if has_cluster_id else 'MISSING'}")
    print(f"  ngram_id: {'EXISTS' if has_ngram_id else 'MISSING'}")

    if version == "13":
        print("\nOK Schema version is already 13. No fix needed.")
        conn.close()
        return 0

    # Case 1: Version < 13 but columns already exist (partial migration)
    if has_lemma_id and has_cluster_id and has_ngram_id:
        print(f"\nWARNING: Schema version is {version} but migration 013 columns already exist!")
        print("This is a partial migration state. Fixing...")

        # Update schema version to 13
        cursor.execute("UPDATE schema_meta SET value='13' WHERE key='schema_version'")
        conn.commit()

        print("OK Updated schema_version to 13")

        # Verify
        cursor.execute("SELECT value FROM schema_meta WHERE key='schema_version'")
        new_version = cursor.fetchone()[0]
        print(f"OK Verified: schema_version = {new_version}")

        conn.close()
        return 0

    # Case 2: Version < 13 and columns don't exist (need migration)
    print(f"\nWARNING: Schema version is {version} and migration 013 not applied.")
    print("The app will apply migration 013 on next startup.")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
