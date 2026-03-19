#!/usr/bin/env python3
"""Check GPU processing database status."""

import sqlite3
from pathlib import Path

db_path = Path(r"M:\V_book\HDLE_Processing\hewiki_gpu_processing.db")

if not db_path.exists():
    print(f"ERROR: Database not found: {db_path}")
    exit(1)

conn = sqlite3.connect(str(db_path))
cur = conn.cursor()

print("=" * 80)
print("Hebrew Wikipedia GPU Processing Status")
print("=" * 80)
print()
print(f"Database: {db_path}")
print(f"Size: {db_path.stat().st_size / (1024**3):.2f} GB")
print()

# Document status
cur.execute(
    """
    SELECT status, COUNT(*) as count
    FROM source_document sd
    JOIN source_corpus sc ON sd.corpus_id = sc.corpus_id
    WHERE sc.project_id = 1
    GROUP BY status
    ORDER BY status
"""
)

print("Document Status:")
print("-" * 80)
total = 0
processed = 0
for status, count in cur.fetchall():
    total += count
    if status == "processed":
        processed = count
    pct = count / 387639 * 100
    print(f"  {status:12s}: {count:7,} ({pct:5.1f}%)")

print(f"  {'TOTAL':12s}: {total:7,}")
print()

# Progress
if total > 0:
    progress_pct = (processed / total) * 100
    print(f"Overall Progress: {processed:,} / {total:,} ({progress_pct:.1f}%)")
    print(f"Remaining: {total - processed:,} documents")
    print()

# Lemma statistics
cur.execute("SELECT COUNT(*) FROM lemma WHERE project_id = 1")
lemma_count = cur.fetchone()[0]

cur.execute(
    """
    SELECT SUM(freq_abs)
    FROM lemma_project_stat
    WHERE project_id = 1
"""
)
token_count = cur.fetchone()[0] or 0

print("Lemma Statistics:")
print("-" * 80)
print(f"  Unique lemmas: {lemma_count:,}")
print(f"  Total tokens: {token_count:,}")
if processed > 0:
    print(f"  Avg tokens/doc: {token_count // processed:,}")
print()

# Latest documents
cur.execute(
    """
    SELECT doc_id, status
    FROM source_document sd
    JOIN source_corpus sc ON sd.corpus_id = sc.corpus_id
    WHERE sc.project_id = 1
      AND status IN ('processed', 'processing')
    ORDER BY doc_id DESC
    LIMIT 5
"""
)

print("Latest processed:")
for doc_id, status in cur.fetchall():
    print(f"  Doc {doc_id}: {status}")
print()

# Processing time
cur.execute(
    """
    SELECT
        MIN(processed_at) as first,
        MAX(processed_at) as last
    FROM source_document sd
    JOIN source_corpus sc ON sd.corpus_id = sc.corpus_id
    WHERE sc.project_id = 1
      AND status = 'processed'
      AND processed_at IS NOT NULL
"""
)
times = cur.fetchone()
if times and times[0]:
    print("Processing timeline:")
    print(f"  Started: {times[0]}")
    print(f"  Latest:  {times[1]}")
    print()

print("=" * 80)
if processed == total:
    print("Status: COMPLETE")
else:
    print(f"Status: IN PROGRESS ({progress_pct:.1f}%)")
print("=" * 80)

conn.close()
