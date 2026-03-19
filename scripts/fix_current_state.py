"""Fix current state: sync lemma is_noise to tm_entry."""

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

    print("=" * 70)
    print("FIXING: Sync lemma is_noise to tm_entry")
    print("=" * 70)

    # Sync all lemmas to tm_entry
    print("\n[Step 1] Syncing lemma -> tm_entry...")
    cursor.execute(
        """
        UPDATE tm_entry
        SET is_noise = (
            SELECT lemma.is_noise
            FROM lemma
            WHERE lemma.lemma_id = tm_entry.lemma_id
        )
        WHERE kind = 'lemma' AND lemma_id IS NOT NULL
    """
    )
    lemma_synced = cursor.rowcount
    print(f"  Synced {lemma_synced} lemma TMEntry records")

    # Sync all clusters to tm_entry
    print("\n[Step 2] Syncing cluster -> tm_entry...")
    cursor.execute(
        """
        UPDATE tm_entry
        SET is_noise = (
            SELECT term_cluster.is_noise
            FROM term_cluster
            WHERE term_cluster.cluster_id = tm_entry.cluster_id
        )
        WHERE kind = 'term_cluster' AND cluster_id IS NOT NULL
    """
    )
    cluster_synced = cursor.rowcount
    print(f"  Synced {cluster_synced} cluster TMEntry records")

    conn.commit()

    # Verify specific lemma
    project_id = 7
    lemma_text = "תתקש"

    cursor.execute(
        "SELECT lemma_id, is_noise FROM lemma WHERE project_id=? AND lemma_text=?",
        (project_id, lemma_text),
    )
    lemma = cursor.fetchone()

    if lemma:
        lemma_id, lemma_is_noise = lemma
        cursor.execute("SELECT tm_id, is_noise FROM tm_entry WHERE lemma_id=?", (lemma_id,))
        tm_entry = cursor.fetchone()

        if tm_entry:
            tm_id, tm_is_noise = tm_entry
            print(f"\n[Verification]")
            print(f"  Lemma {lemma_text}:")
            print(f"    lemma_id={lemma_id}, is_noise={lemma_is_noise}")
            print(f"  TMEntry:")
            print(f"    tm_id={tm_id}, is_noise={tm_is_noise}")

            if lemma_is_noise == tm_is_noise:
                print(f"  OK: Synced correctly!")
            else:
                print(f"  ERROR: Still not synced!")

    conn.close()

    print("\n" + "=" * 70)
    print("SYNC COMPLETE")
    print("=" * 70)
    print(f"Total synced: {lemma_synced + cluster_synced} records")

    return 0


if __name__ == "__main__":
    sys.exit(main())
