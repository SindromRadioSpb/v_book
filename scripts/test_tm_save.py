"""Test TM entry save for term cluster translation."""
import logging
import sys
import io
from pathlib import Path
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.infra.sa_models import TMEntry, TermCluster
from app.domain.normalization import normalize_for_tm
from datetime import datetime

# Set UTF-8 encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

logging.basicConfig(level=logging.INFO)

# Connect to database
db_path = Path(r"J:\Project_Vibe\V_book\hdle_premium.db")
engine = create_engine(f"sqlite:///{db_path}")
Session = sessionmaker(bind=engine)

print("Testing TM entry save/load...")
print("=" * 80)

with Session() as session:
    # Find a term cluster
    project_id = 2  # Тест_Перевод

    stmt = select(TermCluster).where(
        TermCluster.project_id == project_id
    ).limit(1)
    cluster = session.execute(stmt).scalar()

    if not cluster:
        print("No clusters found!")
        exit(1)

    print(f"\nCluster: {cluster.representative_he}")
    print(f"Pinned translation: {cluster.pinned_translation}")

    # Normalize
    normalized = normalize_for_tm("he", cluster.representative_he, "term_cluster")
    src_norm = normalized.norm
    print(f"Normalized: {src_norm}")

    # Check TM entry
    stmt = select(TMEntry).where(
        TMEntry.project_id == project_id,
        TMEntry.kind == "term_cluster",
        TMEntry.src_norm == src_norm,
    )
    tm_entry = session.execute(stmt).scalar()

    if tm_entry:
        print(f"\nTM Entry found:")
        print(f"  Translation: {tm_entry.translation}")
        print(f"  Status: {tm_entry.status}")
        print(f"  Origin: {tm_entry.origin}")
        print(f"  Updated: {tm_entry.updated_at}")
    else:
        print("\nNo TM entry found - this is the issue!")
        print("Translations from batch translate should create TM entries")

    # Check all TM entries for this project
    stmt = select(TMEntry).where(
        TMEntry.project_id == project_id,
        TMEntry.kind == "term_cluster",
    )
    all_entries = session.execute(stmt).scalars().all()

    print(f"\nTotal TM entries for term_cluster: {len(all_entries)}")
    for entry in all_entries[:5]:
        print(f"  - {entry.src_text} → {entry.translation} ({entry.status}, {entry.origin})")

print("\n" + "=" * 80)
