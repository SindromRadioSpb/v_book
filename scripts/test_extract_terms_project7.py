"""Test Extract Terms for Project 7."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.db_service import DBService
from app.main import get_app_dir
from sqlalchemy import select, func
from app.infra.sa_models import DictProject, TermCluster, TMEntry

# Initialize DB
app_dir = get_app_dir()
db_path = app_dir / "hdle.db"
db_service = DBService.initialize(db_path)
session = db_service.get_session()

print("=" * 80)
print("Extract Terms Test - Project 7")
print("=" * 80)
print()

# Check project exists
project = session.execute(
    select(DictProject).where(DictProject.project_id == 7)
).scalar()

if not project:
    print("[ERROR] Project 7 not found!")
    session.close()
    sys.exit(1)

print(f"[OK] Project found: {project.name}")
print(f"     Library ID: {project.library_id}")
print(f"     Languages: {project.src_lang} -> {project.tgt_lang}")
print()

# Note: Skipping document count (requires join through corpus)
# Terms can be extracted from processed documents
print()

# Check existing terms
existing_terms = session.execute(
    select(func.count(TermCluster.cluster_id)).where(
        TermCluster.project_id == 7
    )
).scalar()

print(f"Existing term clusters: {existing_terms}")
print()

# Check tm_entry for terms
existing_tm = session.execute(
    select(func.count(TMEntry.tm_id)).where(
        TMEntry.project_id == 7,
        TMEntry.kind == "term_cluster"
    )
).scalar()

print(f"TM entries for terms: {existing_tm}")
print()

# Check if tm_global links are set
linked_tm = session.execute(
    select(func.count(TMEntry.tm_id)).where(
        TMEntry.project_id == 7,
        TMEntry.kind == "term_cluster",
        TMEntry.tm_global_id.isnot(None)
    )
).scalar()

print(f"TM entries linked to tm_global: {linked_tm}/{existing_tm}")
print()

# Sample some terms
print("Sample terms (first 10, sorted by frequency):")
terms = session.execute(
    select(TermCluster).where(
        TermCluster.project_id == 7
    ).order_by(TermCluster.freq_abs.desc()).limit(10)
).scalars().all()

for i, term in enumerate(terms, 1):
    # Check if has tm_entry
    tm = session.execute(
        select(TMEntry).where(
            TMEntry.project_id == 7,
            TMEntry.cluster_id == term.cluster_id
        )
    ).scalar()

    translation = tm.translation if tm else ""
    tm_global_id = tm.tm_global_id if tm else None

    print(f"   {i}. [Term {term.cluster_id}] (freq={term.freq_abs})")
    print(f"      Translation: '{translation}'")
    print(f"      TM global ID: {tm_global_id}")
    print()

print("=" * 80)
print("RECOMMENDATIONS:")
print("=" * 80)

if existing_terms == 0:
    print("[!] No terms extracted yet. Ready to run Extract Terms.")
    print("    Action: Run Extract Terms in UI")
else:
    print(f"[OK] {existing_terms} terms already extracted.")
    if existing_tm < existing_terms:
        print(f"[!] Only {existing_tm}/{existing_terms} terms have TM entries.")
        print("    Action: Run batch translation or manual editing")
    if linked_tm < existing_tm:
        print(f"[!] Only {linked_tm}/{existing_tm} TM entries linked to tm_global.")
        print("    Action: Run repropagate_tm_global.py")

print()
print("To extract/update terms:")
print("1. Open app: python -m app.main")
print("2. Navigate to project 7")
print("3. Click 'Extract Term' button")
print("4. Monitor for 'database is locked' errors (should be rare now)")
print()

session.close()
