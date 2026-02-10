"""Check Hebrew Wikipedia processing status.

Shows progress of lemma extraction and NLP processing.

Usage:
    python scripts/check_wikipedia_processing.py
"""

import sqlite3
from pathlib import Path
import sys

def check_processing_status():
    """Check Wikipedia processing status."""

    db_path = Path("J:/Project_Vibe/V_book/hdle_premium.db")

    if not db_path.exists():
        print(f"[ERROR] Database not found: {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    print("=" * 70)
    print("Hebrew Wikipedia Processing Status")
    print("=" * 70)
    print()

    # Get Wikipedia project
    cur.execute("""
        SELECT project_id, name, created_at, updated_at
        FROM dict_project
        WHERE name LIKE '%Wikipedia%'
    """)
    projects = cur.fetchall()

    if not projects:
        print("[WARNING] No Wikipedia project found")
        conn.close()
        return

    project_id, name, created_at, updated_at = projects[0]
    print(f"Project: {name}")
    print(f"Project ID: {project_id}")
    print(f"Created: {created_at}")
    print(f"Updated: {updated_at}")
    print()

    # Document status breakdown
    cur.execute(f"""
        SELECT status, COUNT(*) as count
        FROM source_document sd
        JOIN source_corpus sc ON sd.corpus_id = sc.corpus_id
        WHERE sc.project_id = {project_id}
        GROUP BY status
        ORDER BY status
    """)

    print("Document Status:")
    print("-" * 70)

    total = 0
    status_counts = {}
    for status, count in cur.fetchall():
        status_counts[status] = count
        total += count
        print(f"  {status:12s}: {count:6,d} ({count/total*100:5.1f}%)")

    print(f"  {'TOTAL':12s}: {total:6,d}")
    print()

    # Processing progress
    processed = status_counts.get('processed', 0)
    processing = status_counts.get('processing', 0)
    queued = status_counts.get('queued', 0)
    failed = status_counts.get('failed', 0)
    imported = status_counts.get('imported', 0)

    if total > 0:
        progress_pct = (processed / total) * 100
        print(f"Overall Progress: {processed:,} / {total:,} ({progress_pct:.1f}%)")

        if processing > 0:
            print(f"Currently processing: {processing:,} documents")

        if failed > 0:
            print(f"[WARNING] Failed: {failed:,} documents ({failed/total*100:.1f}%)")

        print()

    # Token statistics (check if table exists first)
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='document_token'")
    if cur.fetchone():
        cur.execute(f"""
            SELECT
                COUNT(DISTINCT dt.doc_id) as docs_with_tokens,
                COUNT(*) as total_tokens,
                COUNT(DISTINCT dt.lemma) as unique_lemmas,
                COUNT(DISTINCT dt.pos) as unique_pos
            FROM document_token dt
            JOIN source_document sd ON dt.doc_id = sd.doc_id
            JOIN source_corpus sc ON sd.corpus_id = sc.corpus_id
            WHERE sc.project_id = {project_id}
        """)
        result = cur.fetchone()
    else:
        result = None
        print("[INFO] document_token table not found (processing not started)")
        print()

    if result and result[0] > 0:
        docs_with_tokens, total_tokens, unique_lemmas, unique_pos = result
        print("Token Statistics:")
        print("-" * 70)
        print(f"  Documents with tokens: {docs_with_tokens:,}")
        print(f"  Total tokens: {total_tokens:,}")
        print(f"  Unique lemmas: {unique_lemmas:,}")
        print(f"  Unique POS tags: {unique_pos}")
        print()

    # Term extraction progress (check if table exists first)
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='document_term'")
    if cur.fetchone():
        cur.execute(f"""
            SELECT
                COUNT(DISTINCT doc_id) as docs_with_terms
            FROM document_term dt
            WHERE EXISTS (
                SELECT 1 FROM source_document sd
                JOIN source_corpus sc ON sd.corpus_id = sc.corpus_id
                WHERE sd.doc_id = dt.doc_id AND sc.project_id = {project_id}
            )
        """)
        docs_with_terms = cur.fetchone()[0]
    else:
        docs_with_terms = 0

    if docs_with_terms > 0:
        print("Term Extraction:")
        print("-" * 70)
        print(f"  Documents with terms: {docs_with_terms:,}")
        print()

    # Errors (if any)
    cur.execute(f"""
        SELECT error_message, COUNT(*) as count
        FROM source_document sd
        JOIN source_corpus sc ON sd.corpus_id = sc.corpus_id
        WHERE sc.project_id = {project_id}
            AND status = 'failed'
            AND error_message IS NOT NULL
        GROUP BY error_message
        ORDER BY count DESC
        LIMIT 5
    """)

    errors = cur.fetchall()
    if errors:
        print("Top Errors:")
        print("-" * 70)
        for error_msg, count in errors:
            # Truncate long error messages
            if len(error_msg) > 60:
                error_msg = error_msg[:57] + "..."
            print(f"  {count:4d}x {error_msg}")
        print()

    # Completion estimate
    if processing > 0 or queued > 0:
        remaining = processing + queued + imported
        print("=" * 70)
        print(f"Processing in progress: {remaining:,} documents remaining")
        print()
        print("Status: IN PROGRESS ⏳")
        print()
        print("Run this script again to check progress.")
    elif processed == total:
        print("=" * 70)
        print("Status: COMPLETE ✅")
        print()
        print("All documents processed successfully!")
        print()
        print("Ready to export baseline:")
        print("  python scripts/export_wikipedia_baseline.py")
    else:
        print("=" * 70)
        print(f"Status: INCOMPLETE ({processed}/{total} processed)")
        print()
        if failed > 0:
            print(f"Note: {failed:,} documents failed processing")

    print("=" * 70)

    conn.close()

if __name__ == "__main__":
    check_processing_status()
