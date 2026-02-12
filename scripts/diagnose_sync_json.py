"""Diagnose bidirectional sync issue - JSON output."""

import os
import sys
import sqlite3
import json
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

    results = {
        "project_id": project_id,
        "test_cases": [],
        "statistics": {}
    }

    # Test Case 1: Lemma תתקש
    cursor.execute(
        "SELECT lemma_id, lemma_text, norm_text, is_noise FROM lemma "
        "WHERE project_id=? AND lemma_text=?",
        (project_id, "תתקש")
    )
    lemma = cursor.fetchone()

    test1 = {"name": "Lemma Test", "found": False}

    if lemma:
        lemma_id, lemma_text, norm_text, is_noise = lemma
        test1["found"] = True
        test1["lemma"] = {
            "lemma_id": lemma_id,
            "lemma_text": lemma_text,
            "norm_text": norm_text,
            "is_noise": is_noise,
            "is_noise_label": "NOISE" if is_noise == 1 else "VALID"
        }

        # Check TMEntry by src_text
        cursor.execute(
            "SELECT tm_id, src_text, src_norm, is_noise, lemma_id FROM tm_entry "
            "WHERE project_id=? AND kind='lemma' AND src_text=?",
            (project_id, lemma_text)
        )
        tm_by_text = cursor.fetchall()

        test1["tm_entries_by_text"] = []
        for tm in tm_by_text:
            tm_id, src_text, src_norm, tm_is_noise, linked_lemma_id = tm
            test1["tm_entries_by_text"].append({
                "tm_id": tm_id,
                "src_text": src_text,
                "src_norm": src_norm,
                "is_noise": tm_is_noise,
                "is_noise_label": "NOISE" if tm_is_noise == 1 else "VALID",
                "lemma_id": linked_lemma_id,
                "is_linked": linked_lemma_id is not None,
                "sync_issue": tm_is_noise != is_noise,
                "link_issue": linked_lemma_id is None
            })

        # Check TMEntry by lemma_id
        cursor.execute(
            "SELECT tm_id, src_text, is_noise FROM tm_entry WHERE lemma_id=?",
            (lemma_id,)
        )
        tm_by_id = cursor.fetchall()

        test1["tm_entries_by_lemma_id"] = len(tm_by_id)
        test1["has_linked_entries"] = len(tm_by_id) > 0

    results["test_cases"].append(test1)

    # Test Case 2: Term Cluster תשובה ג
    cursor.execute(
        "SELECT cluster_id, representative_he, norm_text, is_noise FROM term_cluster "
        "WHERE project_id=? AND representative_he=?",
        (project_id, "תשובה ג")
    )
    cluster = cursor.fetchone()

    test2 = {"name": "Term Cluster Test", "found": False}

    if cluster:
        cluster_id, repr_he, norm_text, is_noise = cluster
        test2["found"] = True
        test2["cluster"] = {
            "cluster_id": cluster_id,
            "representative_he": repr_he,
            "norm_text": norm_text,
            "is_noise": is_noise,
            "is_noise_label": "NOISE" if is_noise == 1 else "VALID"
        }

        # Check TMEntry by src_text
        cursor.execute(
            "SELECT tm_id, src_text, src_norm, is_noise, cluster_id FROM tm_entry "
            "WHERE project_id=? AND kind='term_cluster' AND src_text=?",
            (project_id, repr_he)
        )
        tm_by_text = cursor.fetchall()

        test2["tm_entries_by_text"] = []
        for tm in tm_by_text:
            tm_id, src_text, src_norm, tm_is_noise, linked_cluster_id = tm
            test2["tm_entries_by_text"].append({
                "tm_id": tm_id,
                "src_text": src_text,
                "src_norm": src_norm,
                "is_noise": tm_is_noise,
                "is_noise_label": "NOISE" if tm_is_noise == 1 else "VALID",
                "cluster_id": linked_cluster_id,
                "is_linked": linked_cluster_id is not None,
                "sync_issue": tm_is_noise != is_noise,
                "link_issue": linked_cluster_id is None
            })

        # Check TMEntry by cluster_id
        cursor.execute(
            "SELECT tm_id, src_text, is_noise FROM tm_entry WHERE cluster_id=?",
            (cluster_id,)
        )
        tm_by_id = cursor.fetchall()

        test2["tm_entries_by_cluster_id"] = len(tm_by_id)
        test2["has_linked_entries"] = len(tm_by_id) > 0

    results["test_cases"].append(test2)

    # Statistics
    cursor.execute(
        "SELECT COUNT(*) FROM tm_entry WHERE project_id=? AND kind='lemma' AND lemma_id IS NULL",
        (project_id,)
    )
    unlinked_lemmas = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM tm_entry WHERE project_id=? AND kind='term_cluster' AND cluster_id IS NULL",
        (project_id,)
    )
    unlinked_clusters = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM tm_entry WHERE project_id=? AND kind='lemma'",
        (project_id,)
    )
    total_lemma_tm = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM tm_entry WHERE project_id=? AND kind='term_cluster'",
        (project_id,)
    )
    total_cluster_tm = cursor.fetchone()[0]

    results["statistics"] = {
        "total_lemma_tm": total_lemma_tm,
        "linked_lemma_tm": total_lemma_tm - unlinked_lemmas,
        "unlinked_lemma_tm": unlinked_lemmas,
        "total_cluster_tm": total_cluster_tm,
        "linked_cluster_tm": total_cluster_tm - unlinked_clusters,
        "unlinked_cluster_tm": unlinked_clusters
    }

    conn.close()

    # Save to JSON file
    output_file = Path("diagnosis_result.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"Diagnosis saved to: {output_file}")
    print(f"\nQuick Summary:")
    print(f"  Total lemma TMEntry: {total_lemma_tm}")
    print(f"    Linked: {total_lemma_tm - unlinked_lemmas}")
    print(f"    Unlinked: {unlinked_lemmas}")
    print(f"  Total cluster TMEntry: {total_cluster_tm}")
    print(f"    Linked: {total_cluster_tm - unlinked_clusters}")
    print(f"    Unlinked: {unlinked_clusters}")

    if unlinked_lemmas > 0 or unlinked_clusters > 0:
        print(f"\nROOT CAUSE: {unlinked_lemmas + unlinked_clusters} TMEntry records are NOT LINKED!")
        print("  Bidirectional sync requires source_id (lemma_id/cluster_id) to be set.")
        print("  Solution: Run improved backfill script.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
