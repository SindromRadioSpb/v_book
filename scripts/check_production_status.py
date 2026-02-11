#!/usr/bin/env python3
"""Check production Wikipedia processing status."""

import sqlite3
from pathlib import Path

db_path = Path(r"M:\V_book\HDLE\hdle_production_new.db")
conn = sqlite3.connect(str(db_path))
cur = conn.cursor()

print("=" * 70)
print("Hebrew Wikipedia Processing Status (Production)")
print("=" * 70)
print()

# Document status
cur.execute("""
    SELECT status, COUNT(*) as count
    FROM source_document sd
    JOIN source_corpus sc ON sd.corpus_id = sc.corpus_id
    WHERE sc.project_id = 1
    GROUP BY status
    ORDER BY status
""")

print("Document Status:")
print("-" * 70)
total = 0
processed = 0
for status, count in cur.fetchall():
    total += count
    if status == 'processed':
        processed = count
    print(f"  {status:12s}: {count:6,d} ({count/387639*100:5.1f}%)")

print(f"  {'TOTAL':12s}: {total:6,d}")
print()

# Progress
if total > 0:
    progress_pct = (processed / total) * 100
    print(f"Overall Progress: {processed:,} / {total:,} ({progress_pct:.1f}%)")
    remaining = total - processed
    print(f"Remaining: {remaining:,} documents")
    print()

# Lemma statistics
cur.execute("SELECT COUNT(*) FROM lemma WHERE project_id = 1")
lemma_count = cur.fetchone()[0]

cur.execute("""
    SELECT SUM(freq_abs)
    FROM lemma_project_stat
    WHERE project_id = 1
""")
token_count = cur.fetchone()[0] or 0

print("Lemma Statistics:")
print("-" * 70)
print(f"  Unique lemmas: {lemma_count:,}")
print(f"  Total tokens: {token_count:,}")
if processed > 0:
    print(f"  Avg tokens/doc: {token_count//processed:,}")
print()

print("=" * 70)
if processed == total:
    print("Status: COMPLETE")
else:
    print(f"Status: IN PROGRESS ({progress_pct:.1f}%)")
print("=" * 70)

conn.close()
