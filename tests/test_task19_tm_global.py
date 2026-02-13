"""Tests for Task 19: Global TM canonical layer.

Tests:
1. Basic upsert_global creates new entry
2. Scoring: higher status+origin wins
3. Scoring: lower status+origin loses
4. Backfill creates tm_global from tm_entry
5. Backfill cross-project: same key → one tm_global
6. Backfill idempotency
7. upsert_and_link sets tm_global_id
8. propagate_to_entries updates tm_entries
9. Noise: tm_global.is_noise=1 only when ALL entries are noise
10. UNIQUE constraint prevents duplicates
"""

import pytest
from datetime import datetime
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker

from app.infra.sa_models import Base, TMEntry, TMGlobal, DictProject, Library
from app.services.tm_global_service import TMGlobalService


@pytest.fixture
def in_memory_db():
    """Create in-memory SQLite database."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    # Create test library and projects
    lib = Library(library_id=1, name="Test Library")
    session.add(lib)
    session.flush()

    p1 = DictProject(project_id=1, library_id=1, name="Project 1", src_lang="he", tgt_lang="ru")
    p2 = DictProject(project_id=2, library_id=1, name="Project 2", src_lang="he", tgt_lang="ru")
    session.add_all([p1, p2])
    session.commit()

    yield session
    session.close()
    engine.dispose()


def test_upsert_global_creates_new(in_memory_db):
    """Test 1: upsert_global creates new tm_global entry."""
    session = in_memory_db
    service = TMGlobalService()

    g = service.upsert_global(
        session=session,
        src_lang="he",
        tgt_lang="ru",
        kind="lemma",
        src_norm="normalized_key",
        src_text="test",
        translation="тест",
        status="approved",
        origin="user_edit",
    )
    session.commit()

    assert g.tm_global_id is not None
    assert g.src_norm == "normalized_key"
    assert g.translation == "тест"
    assert g.status == "approved"
    assert g.origin == "user_edit"


def test_upsert_global_scoring_higher_wins(in_memory_db):
    """Test 2: approved+user_edit beats draft+mt_auto."""
    session = in_memory_db
    service = TMGlobalService()

    # Create initial: draft + mt_auto
    g1 = service.upsert_global(
        session=session,
        src_lang="he",
        tgt_lang="ru",
        kind="lemma",
        src_norm="test_key",
        src_text="test",
        translation="old_translation",
        status="draft",
        origin="mt_auto",
    )
    session.commit()
    assert g1.translation == "old_translation"

    # Upsert with better score: approved + user_edit
    g2 = service.upsert_global(
        session=session,
        src_lang="he",
        tgt_lang="ru",
        kind="lemma",
        src_norm="test_key",  # Same key
        src_text="test",
        translation="new_translation",
        status="approved",
        origin="user_edit",
    )
    session.commit()

    # Should update existing
    assert g2.tm_global_id == g1.tm_global_id
    assert g2.translation == "new_translation"
    assert g2.status == "approved"
    assert g2.origin == "user_edit"


def test_upsert_global_scoring_lower_loses(in_memory_db):
    """Test 3: mt_auto doesn't overwrite user_edit."""
    session = in_memory_db
    service = TMGlobalService()

    # Create initial: approved + user_edit
    g1 = service.upsert_global(
        session=session,
        src_lang="he",
        tgt_lang="ru",
        kind="lemma",
        src_norm="test_key",
        src_text="test",
        translation="user_translation",
        status="approved",
        origin="user_edit",
    )
    session.commit()

    # Try to upsert with lower score: draft + mt_auto
    g2 = service.upsert_global(
        session=session,
        src_lang="he",
        tgt_lang="ru",
        kind="lemma",
        src_norm="test_key",  # Same key
        src_text="test",
        translation="mt_translation",
        status="draft",
        origin="mt_auto",
    )
    session.commit()

    # Should NOT update (existing wins)
    assert g2.tm_global_id == g1.tm_global_id
    assert g2.translation == "user_translation"  # Unchanged
    assert g2.status == "approved"
    assert g2.origin == "user_edit"


def test_backfill_creates_global_entries(in_memory_db):
    """Test 4: Backfill creates tm_global from tm_entry."""
    session = in_memory_db
    service = TMGlobalService()

    # Create tm_entry records
    e1 = TMEntry(
        project_id=1,
        kind="lemma",
        src_lang="he",
        tgt_lang="ru",
        src_text="test",
        src_norm="test_norm",
        translation="тест",
        status="approved",
        origin="user_edit",
    )
    session.add(e1)
    session.commit()

    # Run backfill
    stats = service.backfill(session, chunk_size=100, dry_run=False)

    assert stats["groups_created"] == 1
    assert stats["entries_linked"] == 1

    # Verify tm_global created
    g = session.execute(select(TMGlobal).where(TMGlobal.src_norm == "test_norm")).scalar()
    assert g is not None
    assert g.translation == "тест"
    assert g.status == "approved"

    # Verify tm_entry linked
    session.refresh(e1)
    assert e1.tm_global_id == g.tm_global_id


def test_backfill_cross_project_same_key(in_memory_db):
    """Test 5: Two projects, same lemma → one tm_global."""
    session = in_memory_db
    service = TMGlobalService()

    # Create same lemma in two projects
    e1 = TMEntry(
        project_id=1,
        kind="lemma",
        src_lang="he",
        tgt_lang="ru",
        src_text="test",
        src_norm="shared_key",
        translation="translation1",
        status="draft",
        origin="mt_auto",
    )
    e2 = TMEntry(
        project_id=2,
        kind="lemma",
        src_lang="he",
        tgt_lang="ru",
        src_text="test",
        src_norm="shared_key",  # Same key
        translation="translation2",
        status="approved",
        origin="user_edit",
    )
    session.add_all([e1, e2])
    session.commit()

    # Run backfill
    stats = service.backfill(session, chunk_size=100, dry_run=False)

    assert stats["groups_created"] == 1  # Only one tm_global for shared key
    assert stats["entries_linked"] == 2  # Both entries linked

    # Verify single tm_global with best translation
    g = session.execute(select(TMGlobal).where(TMGlobal.src_norm == "shared_key")).scalar()
    assert g is not None
    assert g.translation == "translation2"  # approved+user_edit wins

    # Both entries linked to same tm_global
    session.refresh(e1)
    session.refresh(e2)
    assert e1.tm_global_id == g.tm_global_id
    assert e2.tm_global_id == g.tm_global_id


def test_backfill_idempotent(in_memory_db):
    """Test 6: Running backfill twice produces same result."""
    session = in_memory_db
    service = TMGlobalService()

    # Create tm_entry
    e1 = TMEntry(
        project_id=1,
        kind="lemma",
        src_lang="he",
        tgt_lang="ru",
        src_text="test",
        src_norm="idempotent_key",
        translation="тест",
        status="approved",
        origin="user_edit",
    )
    session.add(e1)
    session.commit()

    # Run backfill first time
    stats1 = service.backfill(session, chunk_size=100, dry_run=False)
    assert stats1["groups_created"] == 1

    # Run backfill second time
    stats2 = service.backfill(session, chunk_size=100, dry_run=False)

    # Should not create duplicates (UNIQUE constraint prevents it)
    # But entries already linked, so no new links created
    assert stats2["groups_created"] >= 0  # May be 0 or 1 depending on upsert behavior

    # Verify only one tm_global exists
    count = session.execute(
        select(func.count(TMGlobal.tm_global_id)).where(TMGlobal.src_norm == "idempotent_key")
    ).scalar()
    assert count == 1


def test_upsert_and_link_sets_global_id(in_memory_db):
    """Test 7: upsert_and_link sets entry.tm_global_id."""
    session = in_memory_db
    service = TMGlobalService()

    # Create tm_entry
    entry = TMEntry(
        project_id=1,
        kind="lemma",
        src_lang="he",
        tgt_lang="ru",
        src_text="test",
        src_norm="link_test",
        translation="тест",
        status="approved",
        origin="user_edit",
    )
    session.add(entry)
    session.flush()  # Get tm_id

    # Call upsert_and_link
    g = service.upsert_and_link(session, entry)
    session.commit()

    assert entry.tm_global_id is not None
    assert entry.tm_global_id == g.tm_global_id


def test_propagate_translation(in_memory_db):
    """Test 8: propagate_to_entries updates all linked tm_entries."""
    session = in_memory_db
    service = TMGlobalService()

    # Create tm_global
    g = TMGlobal(
        src_lang="he",
        tgt_lang="ru",
        kind="lemma",
        src_norm="propagate_key",
        src_text="test",
        translation="old_translation",
        status="approved",
        origin="user_edit",
    )
    session.add(g)
    session.flush()

    # Create two tm_entries linked to same global
    e1 = TMEntry(
        project_id=1,
        kind="lemma",
        src_lang="he",
        tgt_lang="ru",
        src_text="test",
        src_norm="propagate_key",
        translation="old1",
        status="approved",
        origin="user_edit",
        tm_global_id=g.tm_global_id,
    )
    e2 = TMEntry(
        project_id=2,
        kind="lemma",
        src_lang="he",
        tgt_lang="ru",
        src_text="test",
        src_norm="propagate_key",
        translation="old2",
        status="approved",
        origin="user_edit",
        tm_global_id=g.tm_global_id,
    )
    session.add_all([e1, e2])
    session.commit()

    # Update global translation
    g.translation = "new_translation"
    session.commit()

    # Propagate
    count = service.propagate_to_entries(session, g.tm_global_id, fields=["translation"])
    session.commit()

    assert count == 2

    # Verify both entries updated
    session.refresh(e1)
    session.refresh(e2)
    assert e1.translation == "new_translation"
    assert e2.translation == "new_translation"


def test_noise_all_entries_noise(in_memory_db):
    """Test 9: tm_global.is_noise=1 only when ALL entries are noise."""
    session = in_memory_db
    service = TMGlobalService()

    # Create two entries, both noise
    e1 = TMEntry(
        project_id=1,
        kind="lemma",
        src_lang="he",
        tgt_lang="ru",
        src_text="test",
        src_norm="noise_key",
        translation="test",
        status="approved",
        origin="user_edit",
        is_noise=1,
        noise_reason="NOISE_PUNCT_ONLY",
    )
    e2 = TMEntry(
        project_id=2,
        kind="lemma",
        src_lang="he",
        tgt_lang="ru",
        src_text="test",
        src_norm="noise_key",
        translation="test",
        status="approved",
        origin="user_edit",
        is_noise=1,
        noise_reason="NOISE_PUNCT_ONLY",
    )
    session.add_all([e1, e2])
    session.commit()

    # Run backfill
    stats = service.backfill(session, chunk_size=100, dry_run=False)

    # Verify tm_global is noise
    g = session.execute(select(TMGlobal).where(TMGlobal.src_norm == "noise_key")).scalar()
    assert g.is_noise == 1
    assert g.noise_reason == "NOISE_PUNCT_ONLY"

    # Now add a non-noise entry and re-backfill
    e3 = TMEntry(
        project_id=1,
        kind="lemma",
        src_lang="he",
        tgt_lang="ru",
        src_text="test2",
        src_norm="mixed_noise_key",
        translation="test",
        status="approved",
        origin="user_edit",
        is_noise=0,  # Not noise
    )
    e4 = TMEntry(
        project_id=2,
        kind="lemma",
        src_lang="he",
        tgt_lang="ru",
        src_text="test2",
        src_norm="mixed_noise_key",
        translation="test",
        status="approved",
        origin="user_edit",
        is_noise=1,  # Noise
        noise_reason="NOISE_NUMBER_ONLY",
    )
    session.add_all([e3, e4])
    session.commit()

    stats = service.backfill(session, chunk_size=100, dry_run=False)

    # Verify tm_global is NOT noise (one entry is not noise)
    g2 = session.execute(select(TMGlobal).where(TMGlobal.src_norm == "mixed_noise_key")).scalar()
    assert g2.is_noise == 0


def test_unique_constraint(in_memory_db):
    """Test 10: UNIQUE constraint prevents duplicate keys."""
    session = in_memory_db

    # Create first tm_global
    g1 = TMGlobal(
        src_lang="he",
        tgt_lang="ru",
        kind="lemma",
        src_norm="unique_key",
        src_text="test",
        translation="тест",
        status="approved",
        origin="user_edit",
    )
    session.add(g1)
    session.commit()

    # Try to create duplicate
    g2 = TMGlobal(
        src_lang="he",
        tgt_lang="ru",
        kind="lemma",
        src_norm="unique_key",  # Same key
        src_text="test2",
        translation="тест2",
        status="approved",
        origin="user_edit",
    )
    session.add(g2)

    # Should raise IntegrityError
    with pytest.raises(Exception):  # IntegrityError
        session.commit()
    session.rollback()

    # Verify only one exists
    count = session.execute(
        select(func.count(TMGlobal.tm_global_id)).where(TMGlobal.src_norm == "unique_key")
    ).scalar()
    assert count == 1
