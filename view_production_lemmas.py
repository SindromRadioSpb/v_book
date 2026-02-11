#!/usr/bin/env python3
"""View top lemmas from production database."""

import sqlite3
from pathlib import Path

db_path = Path(r"M:\V_book\HDLE\hdle_production_new.db")
conn = sqlite3.connect(str(db_path))
cur = conn.cursor()

print("=" * 70)
print("Top 50 Most Frequent Lemmas (Hebrew Wikipedia)")
print("=" * 70)
print()

cur.execute("""
    SELECT 
        l.lemma_text,
        l.pos,
        lps.freq_abs,
        lps.doc_freq
    FROM lemma l
    JOIN lemma_project_stat lps ON l.lemma_id = lps.lemma_id
    WHERE l.project_id = 1
    ORDER BY lps.freq_abs DESC
    LIMIT 50
""")

print(f"{'Rank':<6} {'Lemma':<20} {'POS':<8} {'Frequency':<12} {'Documents':<10}")
print("-" * 70)

for i, (lemma, pos, freq, doc_freq) in enumerate(cur.fetchall(), 1):
    print(f"{i:<6} {lemma:<20} {pos:<8} {freq:<12,} {doc_freq:<10,}")

print()
print("=" * 70)
print(f"Total lemmas: {cur.execute('SELECT COUNT(*) FROM lemma WHERE project_id = 1').fetchone()[0]:,}")
print("=" * 70)

conn.close()
