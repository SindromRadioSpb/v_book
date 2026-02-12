"""Improved backfill script for TMEntry source_id linking.

Fixes:
1. Handle NULL norm_text in term_cluster (match by representative_he)
2. Handle normalization differences (spaces <-> underscores)
3. Sync is_noise after linking
"""

import os
import sys
import sqlite3
from pathlib import Path


def normalize_for_match(text: str) -> str:
    """Normalize text for matching - replace spaces with underscores."""
    if text:
        return text.replace(" ", "_")
    return text


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
    print("=" * 70)
    print("IMPROVED BACKFILL: Link TMEntry to source entities")
    print("=" * 70)

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Step 1: Link Lemmas
    print("\n[Step 1] Linking TMEntry (kind=lemma) to Lemma table...")

    # Get unlinked lemma TMEntry records
    cursor.execute(
        "SELECT tm_id, project_id, src_text, src_norm FROM tm_entry "
        "WHERE kind='lemma' AND lemma_id IS NULL"
    )
    unlinked_lemmas = cursor.fetchall()

    print(f"  Found {len(unlinked_lemmas)} unlinked TMEntry records")

    linked_count = 0
    for tm_id, project_id, src_text, src_norm in unlinked_lemmas:
        # Try to match by norm_text first
        cursor.execute(
            "SELECT lemma_id, is_noise, noise_reason FROM lemma "
            "WHERE project_id=? AND norm_text=?",
            (project_id, src_norm)
        )
        match = cursor.fetchone()

        # If no match, try by lemma_text
        if not match:
            cursor.execute(
                "SELECT lemma_id, is_noise, noise_reason FROM lemma "
                "WHERE project_id=? AND lemma_text=?",
                (project_id, src_text)
            )
            match = cursor.fetchone()

        if match:
            lemma_id, is_noise, noise_reason = match
            # Update TMEntry
            cursor.execute(
                "UPDATE tm_entry SET lemma_id=?, is_noise=?, noise_reason=? WHERE tm_id=?",
                (lemma_id, is_noise, noise_reason, tm_id)
            )
            linked_count += 1

    conn.commit()
    print(f"  Linked {linked_count}/{len(unlinked_lemmas)} lemma TMEntry records")

    # Step 2: Link Term Clusters
    print("\n[Step 2] Linking TMEntry (kind=term_cluster) to TermCluster table...")

    # Get unlinked cluster TMEntry records
    cursor.execute(
        "SELECT tm_id, project_id, src_text, src_norm FROM tm_entry "
        "WHERE kind='term_cluster' AND cluster_id IS NULL"
    )
    unlinked_clusters = cursor.fetchall()

    print(f"  Found {len(unlinked_clusters)} unlinked TMEntry records")

    linked_count = 0
    for tm_id, project_id, src_text, src_norm in unlinked_clusters:
        # Try to match by norm_text first (if cluster.norm_text is not NULL)
        cursor.execute(
            "SELECT cluster_id, is_noise, noise_reason FROM term_cluster "
            "WHERE project_id=? AND norm_text=?",
            (project_id, src_norm)
        )
        match = cursor.fetchone()

        # If no match, try by representative_he (handle NULL norm_text)
        if not match:
            cursor.execute(
                "SELECT cluster_id, is_noise, noise_reason FROM term_cluster "
                "WHERE project_id=? AND representative_he=?",
                (project_id, src_text)
            )
            match = cursor.fetchone()

        # If still no match, try with normalized matching (space/underscore variations)
        if not match:
            # Normalize src_text (replace underscore with space) and try again
            src_text_normalized = src_norm.replace("_", " ") if src_norm else src_text
            cursor.execute(
                "SELECT cluster_id, is_noise, noise_reason FROM term_cluster "
                "WHERE project_id=? AND representative_he=?",
                (project_id, src_text_normalized)
            )
            match = cursor.fetchone()

        if match:
            cluster_id, is_noise, noise_reason = match
            # Update TMEntry
            cursor.execute(
                "UPDATE tm_entry SET cluster_id=?, is_noise=?, noise_reason=? WHERE tm_id=?",
                (cluster_id, is_noise, noise_reason, tm_id)
            )
            linked_count += 1

    conn.commit()
    print(f"  Linked {linked_count}/{len(unlinked_clusters)} cluster TMEntry records")

    # Step 3: Sync is_noise for already linked entries
    print("\n[Step 3] Syncing is_noise for already linked entries...")

    # Sync lemmas
    cursor.execute(
        "UPDATE tm_entry SET is_noise = (SELECT lemma.is_noise FROM lemma WHERE lemma.lemma_id = tm_entry.lemma_id) "
        "WHERE kind='lemma' AND lemma_id IS NOT NULL"
    )
    synced_lemmas = cursor.rowcount

    # Sync clusters
    cursor.execute(
        "UPDATE tm_entry SET is_noise = (SELECT term_cluster.is_noise FROM term_cluster WHERE term_cluster.cluster_id = tm_entry.cluster_id) "
        "WHERE kind='term_cluster' AND cluster_id IS NOT NULL"
    )
    synced_clusters = cursor.rowcount

    conn.commit()
    print(f"  Synced {synced_lemmas} lemma TMEntry records")
    print(f"  Synced {synced_clusters} cluster TMEntry records")

    # Final statistics
    print("\n" + "=" * 70)
    print("FINAL STATISTICS")
    print("=" * 70)

    cursor.execute("SELECT COUNT(*) FROM tm_entry WHERE kind='lemma' AND lemma_id IS NOT NULL")
    linked_lemmas_total = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM tm_entry WHERE kind='lemma'")
    total_lemmas = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM tm_entry WHERE kind='term_cluster' AND cluster_id IS NOT NULL")
    linked_clusters_total = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM tm_entry WHERE kind='term_cluster'")
    total_clusters = cursor.fetchone()[0]

    print(f"\nLemma TMEntry:")
    print(f"  Total: {total_lemmas}")
    print(f"  Linked: {linked_lemmas_total} ({100*linked_lemmas_total/total_lemmas if total_lemmas > 0 else 0:.1f}%)")
    print(f"  Unlinked: {total_lemmas - linked_lemmas_total}")

    print(f"\nCluster TMEntry:")
    print(f"  Total: {total_clusters}")
    print(f"  Linked: {linked_clusters_total} ({100*linked_clusters_total/total_clusters if total_clusters > 0 else 0:.1f}%)")
    print(f"  Unlinked: {total_clusters - linked_clusters_total}")

    conn.close()

    print("\n" + "=" * 70)
    print("BACKFILL COMPLETE")
    print("=" * 70)
    print("\nNext step: Restart the app to test bidirectional sync.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
