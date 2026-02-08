"""Test bulk_resolve to check if it finds TM entries."""
import sys
import io
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Set UTF-8 encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from app.services.translation_service import TranslationService

# Connect to database
db_path = Path(r"J:\Project_Vibe\V_book\hdle_premium.db")
engine = create_engine(f"sqlite:///{db_path}")
Session = sessionmaker(bind=engine)

print("Testing bulk_resolve for term clusters...")
print("=" * 80)

# Terms from test project
items = [
    ("בית ספר", "term_cluster"),
    ("ספר גדול", "term_cluster"),
    ("ספר החדש", "term_cluster"),
    ("בית ספר גדול", "term_cluster"),
    ("הספר", "term_cluster"),
]

with Session() as session:
    translation_service = TranslationService()

    results = translation_service.bulk_resolve(
        session=session,
        items=items,
        src_lang="he",
        tgt_lang="ru",
        project_id=2,  # Тест_Перевод
        allow_draft=True,
    )

    print(f"\nResults: {len(results)} out of {len(items)}")
    print()

    for (src_text, kind), result in results.items():
        print(f"'{src_text}':")
        print(f"  Translation: {result.translation}")
        print(f"  Source: {result.source}")
        print(f"  Status: {result.status}")
        print()

print("=" * 80)
