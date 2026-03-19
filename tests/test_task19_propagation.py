"""Test for Task 19 cross-project translation propagation fix."""

import pytest
from sqlalchemy import create_engine, select
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

    p1 = DictProject(project_id=6, library_id=1, name="Project 6", src_lang="he", tgt_lang="ru")
    p2 = DictProject(project_id=7, library_id=1, name="Project 7", src_lang="he", tgt_lang="ru")
    session.add_all([p1, p2])
    session.commit()

    yield session
    session.close()
    engine.dispose()


def test_cross_project_propagation(in_memory_db):
    """Test: Editing translation in project 7 propagates to project 6.

    Scenario:
    1. Create empty translation in project 6
    2. Create translation in project 7
    3. Both should link to same tm_global
    4. Project 6 should receive translation from project 7 via propagation
    """
    session = in_memory_db
    service = TMGlobalService()

    # Step 1: Create tm_entry in project 6 with empty translation
    entry_p6 = TMEntry(
        project_id=6,
        kind="lemma",
        src_lang="he",
        tgt_lang="ru",
        src_text="test",
        src_norm="test_norm",
        translation="",  # Empty initially
        status="draft",
        origin="mt_auto",
    )
    session.add(entry_p6)
    session.flush()

    # Link to tm_global (this should create tm_global with empty translation)
    g1 = service.upsert_and_link(session, entry_p6)
    session.commit()

    assert entry_p6.tm_global_id is not None
    assert g1.translation == ""  # Initial global has empty translation

    # Step 2: Create tm_entry in project 7 with actual translation
    entry_p7 = TMEntry(
        project_id=7,
        kind="lemma",
        src_lang="he",
        tgt_lang="ru",
        src_text="test",
        src_norm="test_norm",  # Same key
        translation="Тест",  # Has translation
        status="approved",  # Higher score
        origin="user_edit",
    )
    session.add(entry_p7)
    session.flush()

    # Link to tm_global (should update existing global AND propagate to entry_p6)
    g2 = service.upsert_and_link(session, entry_p7)
    session.commit()

    # Verify both entries linked to same tm_global
    assert entry_p7.tm_global_id == entry_p6.tm_global_id
    assert g2.tm_global_id == g1.tm_global_id

    # Verify tm_global was updated with better translation
    session.refresh(g1)
    assert g1.translation == "Тест"
    assert g1.status == "approved"
    assert g1.origin == "user_edit"

    # CRITICAL: Verify project 6 received propagated translation
    session.refresh(entry_p6)
    assert (
        entry_p6.translation == "Тест"
    ), f"Expected project 6 to receive propagated translation, but got: '{entry_p6.translation}'"
    assert entry_p6.status == "approved"
    assert entry_p6.origin == "user_edit"


def test_edit_propagation(in_memory_db):
    """Test: Editing existing translation propagates to all projects.

    Scenario:
    1. Create translation in project 6: "Старый"
    2. Create translation in project 7: "Старый" (same)
    3. Update translation in project 7: "Новый"
    4. Project 6 should receive updated translation
    """
    session = in_memory_db
    service = TMGlobalService()

    # Create initial translations in both projects
    entry_p6 = TMEntry(
        project_id=6,
        kind="lemma",
        src_lang="he",
        tgt_lang="ru",
        src_text="test",
        src_norm="edit_test",
        translation="Старый",
        status="draft",
        origin="mt_auto",
    )
    entry_p7 = TMEntry(
        project_id=7,
        kind="lemma",
        src_lang="he",
        tgt_lang="ru",
        src_text="test",
        src_norm="edit_test",
        translation="Старый",
        status="draft",
        origin="mt_auto",
    )
    session.add_all([entry_p6, entry_p7])
    session.flush()

    service.upsert_and_link(session, entry_p6)
    service.upsert_and_link(session, entry_p7)
    session.commit()

    # Verify initial state
    assert entry_p6.translation == "Старый"
    assert entry_p7.translation == "Старый"

    # Update translation in project 7
    entry_p7.translation = "Новый"
    entry_p7.status = "approved"
    entry_p7.origin = "user_edit"
    session.flush()

    # Call upsert_and_link to propagate
    service.upsert_and_link(session, entry_p7)
    session.commit()

    # Verify propagation to project 6
    session.refresh(entry_p6)
    assert (
        entry_p6.translation == "Новый"
    ), f"Expected project 6 to receive updated translation, but got: '{entry_p6.translation}'"
    assert entry_p6.status == "approved"


def test_no_overwrite_higher_score(in_memory_db):
    """Test: Lower-scored translation doesn't overwrite higher-scored one.

    Scenario:
    1. Create approved+user_edit translation in project 6: "Хороший"
    2. Create draft+mt_auto translation in project 7: "Плохой"
    3. Project 6 should keep "Хороший" (higher score wins)
    4. Project 7 should receive "Хороший" from global
    """
    session = in_memory_db
    service = TMGlobalService()

    # Create high-score translation in project 6
    entry_p6 = TMEntry(
        project_id=6,
        kind="lemma",
        src_lang="he",
        tgt_lang="ru",
        src_text="test",
        src_norm="score_test",
        translation="Хороший",
        status="approved",
        origin="user_edit",
    )
    session.add(entry_p6)
    session.flush()

    service.upsert_and_link(session, entry_p6)
    session.commit()

    # Create low-score translation in project 7
    entry_p7 = TMEntry(
        project_id=7,
        kind="lemma",
        src_lang="he",
        tgt_lang="ru",
        src_text="test",
        src_norm="score_test",
        translation="Плохой",
        status="draft",
        origin="mt_auto",
    )
    session.add(entry_p7)
    session.flush()

    service.upsert_and_link(session, entry_p7)
    session.commit()

    # Verify project 6 unchanged
    session.refresh(entry_p6)
    assert entry_p6.translation == "Хороший"
    assert entry_p6.status == "approved"

    # Verify project 7 received higher-scored translation from global
    session.refresh(entry_p7)
    assert (
        entry_p7.translation == "Хороший"
    ), f"Expected project 7 to receive higher-scored translation, but got: '{entry_p7.translation}'"
    assert entry_p7.status == "approved"
