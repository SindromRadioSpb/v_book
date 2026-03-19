"""Diagnostic script for Task 19 tm_global implementation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.db_service import DBService
from app.main import get_app_dir
from sqlalchemy import select, func, text


def main():
    # Use default production DB path
    app_dir = get_app_dir()
    db_path = app_dir / "hdle.db"
    db_service = DBService.initialize(db_path)
    session = db_service.get_session()

    print("=" * 80)
    print("Task 19 Diagnostic Report")
    print("=" * 80)

    # 1. Check schema version
    print("\n1. Schema Version:")
    result = session.execute(
        text("SELECT value FROM schema_meta WHERE key='schema_version'")
    ).scalar()
    print(f"   Current schema version: {result}")
    if int(result) < 15:
        print("   ❌ ERROR: Migration 015 NOT applied! Run migrations first.")
        session.close()
        return
    else:
        print("   ✅ Migration 015 applied")

    # 2. Check tm_global table exists
    print("\n2. tm_global table:")
    try:
        from app.infra.sa_models import TMGlobal

        count = session.execute(select(func.count(TMGlobal.tm_global_id))).scalar()
        print(f"   ✅ tm_global table exists")
        print(f"   Total tm_global rows: {count}")
    except Exception as e:
        print(f"   ❌ ERROR: tm_global table issue: {e}")
        session.close()
        return

    # 3. Check tm_entry.tm_global_id column
    print("\n3. tm_entry.tm_global_id column:")
    try:
        from app.infra.sa_models import TMEntry

        linked = session.execute(
            select(func.count(TMEntry.tm_id)).where(TMEntry.tm_global_id.isnot(None))
        ).scalar()
        total = session.execute(select(func.count(TMEntry.tm_id))).scalar()
        print(f"   Total tm_entry rows: {total}")
        print(f"   Linked to tm_global: {linked}")
        print(f"   Unlinked: {total - linked}")
        if linked == 0 and total > 0:
            print("   ❌ WARNING: No tm_entry rows linked to tm_global. Backfill needed!")
        elif linked < total:
            print("   ⚠️  WARNING: Some tm_entry rows not linked. Backfill may be needed.")
        else:
            print("   ✅ All tm_entry rows linked")
    except Exception as e:
        print(f"   ❌ ERROR: {e}")

    # 4. Check specific test case: lemma אוסטניטי in projects 6 and 7
    print("\n4. Test case: lemma 'אוסטניטי' in projects 6 and 7:")
    from app.domain.normalization.normalizer import normalize_for_tm

    # Normalize the lemma
    test_lemma = "אוסטניטי"
    normalized = normalize_for_tm(src_lang="he", text=test_lemma, kind="lemma")
    src_norm = normalized.norm
    print(f"   Source text: {test_lemma}")
    print(f"   Normalized: {src_norm}")

    # Check tm_entry for projects 6 and 7
    entries = (
        session.execute(
            select(TMEntry)
            .where(
                TMEntry.project_id.in_([6, 7]),
                TMEntry.kind == "lemma",
                TMEntry.src_norm == src_norm,
            )
            .order_by(TMEntry.project_id)
        )
        .scalars()
        .all()
    )

    if not entries:
        print(f"   ⚠️  No tm_entry found for '{test_lemma}' in projects 6 or 7")
    else:
        print(f"   Found {len(entries)} tm_entry rows:")
        for e in entries:
            print(
                f"     - Project {e.project_id}: tm_id={e.tm_id}, translation='{e.translation}', "
                f"tm_global_id={e.tm_global_id}, status={e.status}, origin={e.origin}"
            )

    # Check tm_global for this lemma
    global_entry = session.execute(
        select(TMGlobal).where(
            TMGlobal.src_lang == "he", TMGlobal.kind == "lemma", TMGlobal.src_norm == src_norm
        )
    ).scalar()

    if global_entry:
        print(f"\n   tm_global row:")
        print(f"     - tm_global_id: {global_entry.tm_global_id}")
        print(f"     - translation: '{global_entry.translation}'")
        print(f"     - status: {global_entry.status}")
        print(f"     - origin: {global_entry.origin}")
        print(f"     - source_tm_id: {global_entry.source_tm_id}")
    else:
        print(f"\n   ⚠️  No tm_global row found for '{test_lemma}'")

    # 5. Check recent translations (last 10)
    print("\n5. Recent tm_entry updates (last 10):")
    recent = (
        session.execute(select(TMEntry).order_by(TMEntry.updated_at.desc()).limit(10))
        .scalars()
        .all()
    )

    for e in recent:
        print(
            f"   - tm_id={e.tm_id}, project_id={e.project_id}, kind={e.kind}, "
            f"src_text='{e.src_text[:20]}', translation='{e.translation[:30]}', "
            f"tm_global_id={e.tm_global_id}, updated_at={e.updated_at}"
        )

    # 6. Summary
    print("\n" + "=" * 80)
    print("SUMMARY:")
    print("=" * 80)

    if int(result) >= 15:
        print("✅ Migration 015 applied")
    else:
        print("❌ Migration 015 NOT applied")

    if count > 0:
        print(f"✅ tm_global has {count} rows")
    else:
        print("❌ tm_global is empty - backfill needed")

    if linked == total and total > 0:
        print(f"✅ All {total} tm_entry rows linked")
    elif linked > 0:
        print(f"⚠️  Only {linked}/{total} tm_entry rows linked - backfill needed")
    else:
        print(f"❌ No tm_entry rows linked - backfill needed")

    session.close()


if __name__ == "__main__":
    main()
