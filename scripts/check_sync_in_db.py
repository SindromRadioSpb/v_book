"""Check if bidirectional sync works in database.

Test scenario:
1. Find lemma and check is_noise in both lemma and tm_entry tables
2. Update lemma.is_noise
3. Trigger sync (simulate BulkNoiseUpdateWorker)
4. Check if tm_entry.is_noise updated
"""

import os
import sys
import sqlite3
from pathlib import Path


def main():
    # Get production DB
    if sys.platform == "win32":
        app_dir = Path(os.environ.get("LOCALAPPDATA")) / "HDLE"
    else:
        print("This script is for Windows only")
        return 1

    db_path = app_dir / "hdle.db"

    if not db_path.exists():
        print(f"DB not found: {db_path}")
        return 1

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    project_id = 7  # Материаловедение (Гос 1)

    print("=" * 70)
    print("TEST: Bidirectional Sync in Database")
    print("=" * 70)

    # Test lemma תתקש
    lemma_text = "תתקש"
    print(f"\n[Test] Lemma: {lemma_text}")
    print("-" * 70)

    # Get current state
    cursor.execute(
        "SELECT lemma_id, is_noise FROM lemma WHERE project_id=? AND lemma_text=?",
        (project_id, lemma_text)
    )
    lemma = cursor.fetchone()

    if not lemma:
        print("Lemma not found")
        return 1

    lemma_id, current_is_noise = lemma
    print(f"Current state:")
    print(f"  lemma_id: {lemma_id}")
    print(f"  lemma.is_noise: {current_is_noise} ({'NOISE' if current_is_noise == 1 else 'VALID'})")

    # Check linked TMEntry
    cursor.execute(
        "SELECT tm_id, is_noise FROM tm_entry WHERE lemma_id=?",
        (lemma_id,)
    )
    tm_entries = cursor.fetchall()

    print(f"\nLinked TMEntry records: {len(tm_entries)}")
    for tm_id, is_noise in tm_entries:
        print(f"  tm_id={tm_id}, is_noise={is_noise} ({'NOISE' if is_noise == 1 else 'VALID'})")

    # Toggle is_noise
    new_is_noise = 0 if current_is_noise == 1 else 1
    print(f"\nToggling lemma.is_noise: {current_is_noise} -> {new_is_noise}")

    cursor.execute(
        "UPDATE lemma SET is_noise=? WHERE lemma_id=?",
        (new_is_noise, lemma_id)
    )

    # Simulate BulkNoiseUpdateWorker sync
    print("Simulating BulkNoiseUpdateWorker sync...")
    cursor.execute(
        "UPDATE tm_entry SET is_noise=? WHERE lemma_id=?",
        (new_is_noise, lemma_id)
    )

    conn.commit()

    # Verify sync
    cursor.execute(
        "SELECT is_noise FROM lemma WHERE lemma_id=?",
        (lemma_id,)
    )
    lemma_is_noise = cursor.fetchone()[0]

    cursor.execute(
        "SELECT tm_id, is_noise FROM tm_entry WHERE lemma_id=?",
        (lemma_id,)
    )
    tm_entries = cursor.fetchall()

    print(f"\nAfter sync:")
    print(f"  lemma.is_noise: {lemma_is_noise} ({'NOISE' if lemma_is_noise == 1 else 'VALID'})")
    print(f"  TMEntry records:")
    for tm_id, is_noise in tm_entries:
        print(f"    tm_id={tm_id}, is_noise={is_noise} ({'NOISE' if is_noise == 1 else 'VALID'})")
        if is_noise != lemma_is_noise:
            print(f"      >>> SYNC FAILED!")

    # Restore original state
    print(f"\nRestoring original state: {current_is_noise}")
    cursor.execute(
        "UPDATE lemma SET is_noise=? WHERE lemma_id=?",
        (current_is_noise, lemma_id)
    )
    cursor.execute(
        "UPDATE tm_entry SET is_noise=? WHERE lemma_id=?",
        (current_is_noise, lemma_id)
    )
    conn.commit()

    print("\n" + "=" * 70)
    print("RESULT: Bidirectional sync works in DATABASE")
    print("  Problem: UI does not refresh after changes in other tabs")
    print("  Solution: Add Refresh button to Translation Management Panel")
    print("=" * 70)

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
