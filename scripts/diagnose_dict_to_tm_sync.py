"""Diagnose why Dictionary -> TM Panel sync doesn't work."""

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
    lemma_text = "תתקש"

    print("=" * 70)
    print("DIAGNOSIS: Dictionary -> TM Panel Sync")
    print("=" * 70)
    print(f"Project ID: {project_id}")
    print(f"Lemma text: {lemma_text}")
    print("-" * 70)

    # Step 1: Check lemma state
    cursor.execute(
        "SELECT lemma_id, is_noise, noise_reason FROM lemma WHERE project_id=? AND lemma_text=?",
        (project_id, lemma_text)
    )
    lemma = cursor.fetchone()

    if not lemma:
        print("ERROR: Lemma not found")
        return 1

    lemma_id, lemma_is_noise, lemma_noise_reason = lemma
    print(f"\n[Lemma State]")
    print(f"  lemma_id: {lemma_id}")
    print(f"  is_noise: {lemma_is_noise} ({'NOISE' if lemma_is_noise == 1 else 'VALID'})")
    print(f"  noise_reason: {lemma_noise_reason}")

    # Step 2: Check ALL TMEntry records for this lemma
    # By src_text
    cursor.execute(
        "SELECT tm_id, src_text, is_noise, lemma_id, noise_reason FROM tm_entry "
        "WHERE project_id=? AND kind='lemma' AND src_text=?",
        (project_id, lemma_text)
    )
    tm_by_text = cursor.fetchall()

    print(f"\n[TMEntry by src_text='{lemma_text}']")
    print(f"  Found {len(tm_by_text)} records:")
    for tm_id, src_text, is_noise, linked_lemma_id, noise_reason in tm_by_text:
        print(f"\n  tm_id={tm_id}:")
        print(f"    src_text: {src_text}")
        print(f"    is_noise: {is_noise} ({'NOISE' if is_noise == 1 else 'VALID'})")
        print(f"    lemma_id: {linked_lemma_id} ({'LINKED' if linked_lemma_id else 'NOT LINKED'})")
        print(f"    noise_reason: {noise_reason}")

        if linked_lemma_id != lemma_id:
            print(f"    >>> PROBLEM: lemma_id mismatch! Expected {lemma_id}, got {linked_lemma_id}")

        if is_noise != lemma_is_noise:
            print(f"    >>> SYNC ISSUE: Lemma is_noise={lemma_is_noise}, TMEntry is_noise={is_noise}")

    # By lemma_id
    cursor.execute(
        "SELECT tm_id, src_text, is_noise FROM tm_entry WHERE lemma_id=?",
        (lemma_id,)
    )
    tm_by_id = cursor.fetchall()

    print(f"\n[TMEntry by lemma_id={lemma_id}]")
    print(f"  Found {len(tm_by_id)} records:")
    for tm_id, src_text, is_noise in tm_by_id:
        print(f"  tm_id={tm_id}, src_text={src_text}, is_noise={is_noise}")

    # Step 3: Check if there are multiple TMEntry for same lemma
    if len(tm_by_text) > 1:
        print(f"\n>>> WARNING: Multiple TMEntry records for same lemma!")
        print(f"    This can cause confusion - which one is shown in TM Panel?")

    # Step 4: Simulate what happens when user marks lemma as Noise in Dictionary
    print("\n" + "=" * 70)
    print("SIMULATING: User marks lemma as Noise in Dictionary")
    print("=" * 70)

    print("\n[Step 1] Update lemma.is_noise = 1")
    cursor.execute("UPDATE lemma SET is_noise=1 WHERE lemma_id=?", (lemma_id,))

    print("[Step 2] BulkNoiseUpdateWorker should sync TMEntry")
    print("  Expected: UPDATE tm_entry SET is_noise=1 WHERE lemma_id=?")

    # Check what IDs would be updated
    cursor.execute("SELECT tm_id FROM tm_entry WHERE lemma_id=?", (lemma_id,))
    ids_to_update = [row[0] for row in cursor.fetchall()]
    print(f"  TMEntry IDs to update: {ids_to_update}")

    # Rollback (don't actually change)
    conn.rollback()

    # Step 5: Check actual sync code in workers.py
    print("\n" + "=" * 70)
    print("CHECKING: BulkNoiseUpdateWorker sync code")
    print("=" * 70)

    with open("app/ui/workers.py", "r", encoding="utf-8") as f:
        content = f.read()

    # Find the sync code
    if "TMEntry.lemma_id.in_(chunk_ids)" in content:
        print("OK: Sync code exists in workers.py")

        # Check the exact code
        import re
        pattern = r"if self\.model_class == \"Lemma\":.*?session\.execute\(sync_stmt\)"
        match = re.search(pattern, content, re.DOTALL)
        if match:
            print("\n[Sync Code Found]:")
            print(match.group(0)[:500])
    else:
        print("ERROR: Sync code NOT found in workers.py!")

    conn.close()

    print("\n" + "=" * 70)
    print("DIAGNOSIS COMPLETE")
    print("=" * 70)
    print("\nPlease check:")
    print("1. Are all TMEntry records linked (lemma_id set)?")
    print("2. Does BulkNoiseUpdateWorker execute sync code?")
    print("3. Does Refresh actually reload from DB?")

    return 0


if __name__ == "__main__":
    sys.exit(main())
