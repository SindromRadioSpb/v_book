"""Check specific lemma in projects 6 and 7."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.db_service import DBService
from app.main import get_app_dir
from sqlalchemy import select
from app.infra.sa_models import TMGlobal, TMEntry
from app.domain.normalization.normalizer import normalize_for_tm

app_dir = get_app_dir()
db_path = app_dir / "hdle.db"
db_service = DBService.initialize(db_path)
session = db_service.get_session()

test_lemma = "אוסטניטי"
normalized = normalize_for_tm(lang="he", text=test_lemma, kind="lemma")
src_norm = normalized.norm

output_file = Path(__file__).parent.parent / "lemma_check_result.txt"

with open(output_file, "w", encoding="utf-8") as f:
    f.write(f"Test lemma: {test_lemma}\n")
    f.write(f"Normalized: {src_norm}\n")
    f.write("\n")

    # Check tm_entry in projects 6 and 7
    f.write("tm_entry rows:\n")
    entries = session.execute(
        select(TMEntry).where(
            TMEntry.project_id.in_([6, 7]),
            TMEntry.kind == "lemma",
            TMEntry.src_norm == src_norm
        ).order_by(TMEntry.project_id)
    ).scalars().all()

    if entries:
        for e in entries:
            f.write(f"  Project {e.project_id}: tm_id={e.tm_id}, translation=\"{e.translation}\", "
                   f"tm_global_id={e.tm_global_id}, status={e.status}, origin={e.origin}\n")
    else:
        f.write("  No entries found\n")
    f.write("\n")

    # Check tm_global
    f.write("tm_global row:\n")
    global_entry = session.execute(
        select(TMGlobal).where(
            TMGlobal.src_lang == "he",
            TMGlobal.kind == "lemma",
            TMGlobal.src_norm == src_norm
        )
    ).scalar()

    if global_entry:
        f.write(f"  tm_global_id: {global_entry.tm_global_id}\n")
        f.write(f"  translation: \"{global_entry.translation}\"\n")
        f.write(f"  status: {global_entry.status}\n")
        f.write(f"  origin: {global_entry.origin}\n")
        f.write(f"  source_tm_id: {global_entry.source_tm_id}\n")
    else:
        f.write("  No global entry found\n")

session.close()

print(f"Results written to: {output_file}")
