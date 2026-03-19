"""Diagnose bidirectional sync issue."""

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

    print(f"Production DB: {db_path}\n")

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Find project
    project_id = 7  # Материаловедение (Гос 1)

    print("=" * 70)
    print("DIAGNOSIS: Bidirectional Sync Issue")
    print("=" * 70)

    # Test Case 1: Lemma תתקש
    print("\n[Test Case 1] Lemma (Hebrew text)")
    print("-" * 70)

    cursor.execute(
        "SELECT lemma_id, lemma_text, norm_text, is_noise FROM lemma "
        "WHERE project_id=? AND lemma_text=?",
        (project_id, "תתקש"),
    )
    lemma = cursor.fetchone()

    if lemma:
        lemma_id, lemma_text, norm_text, is_noise = lemma
        print(f"Lemma found:")
        print(f"  lemma_id: {lemma_id}")
        print(f"  lemma_text: {lemma_text}")
        print(f"  norm_text: {norm_text}")
        print(f"  is_noise: {is_noise} ({'NOISE' if is_noise == 1 else 'VALID'})")

        # Check TMEntry by src_text
        cursor.execute(
            "SELECT tm_id, src_text, src_norm, is_noise, lemma_id FROM tm_entry "
            "WHERE project_id=? AND kind='lemma' AND src_text=?",
            (project_id, lemma_text),
        )
        tm_by_text = cursor.fetchall()

        print(f"\nTMEntry records (matched by src_text='{lemma_text}'): {len(tm_by_text)}")
        for tm in tm_by_text:
            tm_id, src_text, src_norm, tm_is_noise, linked_lemma_id = tm
            print(f"  tm_id={tm_id}:")
            print(f"    src_text: {src_text}")
            print(f"    src_norm: {src_norm}")
            print(f"    is_noise: {tm_is_noise} ({'NOISE' if tm_is_noise == 1 else 'VALID'})")
            print(
                f"    lemma_id: {linked_lemma_id} ({'LINKED' if linked_lemma_id else 'NOT LINKED'})"
            )

            if tm_is_noise != is_noise:
                print(
                    f"    >>> SYNC ISSUE: Lemma is_noise={is_noise}, TMEntry is_noise={tm_is_noise}"
                )
            if not linked_lemma_id:
                print(f"    >>> LINK ISSUE: TMEntry not linked to lemma (lemma_id is NULL)")

        # Check TMEntry by lemma_id
        cursor.execute(
            "SELECT tm_id, src_text, is_noise FROM tm_entry WHERE lemma_id=?", (lemma_id,)
        )
        tm_by_id = cursor.fetchall()

        print(f"\nTMEntry records (linked by lemma_id={lemma_id}): {len(tm_by_id)}")
        if not tm_by_id:
            print("  >>> NO RECORDS LINKED - This is the problem!")
    else:
        print("Lemma not found in database")

    # Test Case 2: Term Cluster תשובה ג
    print("\n" + "=" * 70)
    print("[Test Case 2] Term Cluster (Hebrew text)")
    print("-" * 70)

    cursor.execute(
        "SELECT cluster_id, representative_he, norm_text, is_noise FROM term_cluster "
        "WHERE project_id=? AND representative_he=?",
        (project_id, "תשובה ג"),
    )
    cluster = cursor.fetchone()

    if cluster:
        cluster_id, repr_he, norm_text, is_noise = cluster
        print(f"Cluster found:")
        print(f"  cluster_id: {cluster_id}")
        print(f"  representative_he: {repr_he}")
        print(f"  norm_text: {norm_text}")
        print(f"  is_noise: {is_noise} ({'NOISE' if is_noise == 1 else 'VALID'})")

        # Check TMEntry by src_text
        cursor.execute(
            "SELECT tm_id, src_text, src_norm, is_noise, cluster_id FROM tm_entry "
            "WHERE project_id=? AND kind='term_cluster' AND src_text=?",
            (project_id, repr_he),
        )
        tm_by_text = cursor.fetchall()

        print(f"\nTMEntry records (matched by src_text='{repr_he}'): {len(tm_by_text)}")
        for tm in tm_by_text:
            tm_id, src_text, src_norm, tm_is_noise, linked_cluster_id = tm
            print(f"  tm_id={tm_id}:")
            print(f"    src_text: {src_text}")
            print(f"    src_norm: {src_norm}")
            print(f"    is_noise: {tm_is_noise} ({'NOISE' if tm_is_noise == 1 else 'VALID'})")
            print(
                f"    cluster_id: {linked_cluster_id} ({'LINKED' if linked_cluster_id else 'NOT LINKED'})"
            )

            if tm_is_noise != is_noise:
                print(
                    f"    >>> SYNC ISSUE: Cluster is_noise={is_noise}, TMEntry is_noise={tm_is_noise}"
                )
            if not linked_cluster_id:
                print(f"    >>> LINK ISSUE: TMEntry not linked to cluster (cluster_id is NULL)")

        # Check TMEntry by cluster_id
        cursor.execute(
            "SELECT tm_id, src_text, is_noise FROM tm_entry WHERE cluster_id=?", (cluster_id,)
        )
        tm_by_id = cursor.fetchall()

        print(f"\nTMEntry records (linked by cluster_id={cluster_id}): {len(tm_by_id)}")
        if not tm_by_id:
            print("  >>> NO RECORDS LINKED - This is the problem!")
    else:
        print("Cluster not found in database")

    # Summary
    print("\n" + "=" * 70)
    print("DIAGNOSIS SUMMARY")
    print("=" * 70)

    # Count total unlinked TMEntry records
    cursor.execute(
        "SELECT COUNT(*) FROM tm_entry WHERE project_id=? AND kind='lemma' AND lemma_id IS NULL",
        (project_id,),
    )
    unlinked_lemmas = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM tm_entry WHERE project_id=? AND kind='term_cluster' AND cluster_id IS NULL",
        (project_id,),
    )
    unlinked_clusters = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM tm_entry WHERE project_id=? AND kind='lemma'", (project_id,)
    )
    total_lemma_tm = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM tm_entry WHERE project_id=? AND kind='term_cluster'", (project_id,)
    )
    total_cluster_tm = cursor.fetchone()[0]

    print(f"\nProject {project_id} Statistics:")
    print(f"  Lemma TMEntry records: {total_lemma_tm}")
    print(f"    Linked (lemma_id set): {total_lemma_tm - unlinked_lemmas}")
    print(f"    Unlinked (lemma_id NULL): {unlinked_lemmas}")

    print(f"\n  Term Cluster TMEntry records: {total_cluster_tm}")
    print(f"    Linked (cluster_id set): {total_cluster_tm - unlinked_clusters}")
    print(f"    Unlinked (cluster_id NULL): {unlinked_clusters}")

    if unlinked_lemmas > 0 or unlinked_clusters > 0:
        print("\n>>> ROOT CAUSE: TMEntry records are NOT LINKED to source entities!")
        print("    Bidirectional sync requires lemma_id/cluster_id to be set.")
        print("    Migration 013 backfill did not link these records.")
        print("\nSOLUTION: Run improved backfill to link existing TMEntry records.")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
