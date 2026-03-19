"""Tests for reference project service logic (PATCH-01).

Tests ProjectService reference corpus behavior:
- get_default_reference_project() determinism and fallback
- create_project() auto-assign reference
- delete_project() guard against reference corpus deletion
"""

import pytest
import tempfile
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.infra.sa_models import Base, Library, DictProject, SourceCorpus
from app.services.project_service import ProjectService
from app.services.db_service import DBService
from app.domain.exceptions import ReferenceCorpusReadonlyError


@pytest.fixture
def temp_db():
    """Create temporary database for testing using SQL migrations."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    # Apply SQL migrations directly
    migrations_dir = Path("app/infra/migrations")
    migration_files = sorted(migrations_dir.glob("*.sql"))

    conn = sqlite3.connect(str(db_path))
    try:
        for migration_file in migration_files:
            with open(migration_file, "r", encoding="utf-8") as f:
                sql = f.read()
                conn.executescript(sql)
        conn.commit()
    finally:
        conn.close()

    # Initialize DBService
    DBService.initialize(str(db_path))

    yield db_path

    # Cleanup: Close DBService connections and reset singleton
    DBService._instance = None

    # Now can safely delete
    try:
        db_path.unlink()
    except PermissionError:
        pass  # File still locked, skip cleanup


@pytest.fixture
def session(temp_db):
    """Create database session."""
    db_service = DBService.get_instance()
    with db_service.get_session() as sess:
        yield sess


@pytest.fixture
def project_service(temp_db):
    """Create ProjectService instance (requires temp_db to initialize DBService)."""
    return ProjectService()


@pytest.fixture
def library(session):
    """Create default library."""
    lib = Library(name="Test Library")
    session.add(lib)
    session.commit()
    session.refresh(lib)
    return lib


# ============================================================================
# get_default_reference_project() tests
# ============================================================================


def test_get_default_reference_project_prefers_is_general_corpus(project_service, session, library):
    """get_default_reference_project() prefers is_general_corpus=1."""
    # Create projects: one with is_general_corpus=1, one by name
    ref_corpus = DictProject(
        library_id=library.library_id,
        name="My Reference Corpus",
        is_general_corpus=1,
    )
    hewiki = DictProject(
        library_id=library.library_id,
        name="Hebrew Wikipedia Baseline",
        is_general_corpus=0,
    )
    session.add_all([ref_corpus, hewiki])
    session.commit()
    session.refresh(ref_corpus)
    session.refresh(hewiki)

    # Should return ref_corpus (is_general_corpus=1), not hewiki
    result = project_service.get_default_reference_project(session)
    assert result == ref_corpus.project_id


def test_get_default_reference_project_fallback_by_name(project_service, session, library):
    """get_default_reference_project() falls back to 'Hebrew Wikipedia Baseline' by name."""
    # Create projects: no is_general_corpus=1, but one named HEWiki
    proj_a = DictProject(
        library_id=library.library_id,
        name="Project A",
        is_general_corpus=0,
    )
    hewiki = DictProject(
        library_id=library.library_id,
        name="Hebrew Wikipedia Baseline",
        is_general_corpus=0,
    )
    session.add_all([proj_a, hewiki])
    session.commit()
    session.refresh(hewiki)

    # Should return hewiki by name
    result = project_service.get_default_reference_project(session)
    assert result == hewiki.project_id


def test_get_default_reference_project_deterministic_lowest_id(project_service, session, library):
    """get_default_reference_project() returns lowest project_id when multiple is_general_corpus=1."""
    # Create multiple reference corpora
    ref1 = DictProject(
        library_id=library.library_id,
        name="Reference Corpus 1",
        is_general_corpus=1,
    )
    ref2 = DictProject(
        library_id=library.library_id,
        name="Reference Corpus 2",
        is_general_corpus=1,
    )
    session.add_all([ref1, ref2])
    session.commit()
    session.refresh(ref1)
    session.refresh(ref2)

    # Should return lowest project_id (deterministic)
    result = project_service.get_default_reference_project(session)
    expected = min(ref1.project_id, ref2.project_id)
    assert result == expected


def test_get_default_reference_project_returns_none_if_not_found(project_service, session, library):
    """get_default_reference_project() returns None if no reference corpus exists."""
    # Create project without is_general_corpus=1 or HEWiki name
    proj = DictProject(
        library_id=library.library_id,
        name="Normal Project",
        is_general_corpus=0,
    )
    session.add(proj)
    session.commit()

    # Should return None
    result = project_service.get_default_reference_project(session)
    assert result is None


# ============================================================================
# create_project() auto-assign tests
# ============================================================================


def test_create_project_auto_assign_reference_by_default(project_service, session, library):
    """create_project() auto-assigns reference corpus by default."""
    # Create reference corpus
    ref = DictProject(
        library_id=library.library_id,
        name="Reference Corpus",
        is_general_corpus=1,
    )
    session.add(ref)
    session.commit()
    session.refresh(ref)

    # Create new project (auto_assign_reference=True by default)
    new_proj = project_service.create_project(
        session,
        name="New Project",
        description="Test",
        library=library,
    )

    # Should have reference assigned
    assert new_proj.general_corpus_id == ref.project_id


def test_create_project_can_disable_auto_assign_reference(project_service, session, library):
    """create_project() respects auto_assign_reference=False."""
    # Create reference corpus
    ref = DictProject(
        library_id=library.library_id,
        name="Reference Corpus",
        is_general_corpus=1,
    )
    session.add(ref)
    session.commit()

    # Create new project with auto_assign_reference=False
    new_proj = project_service.create_project(
        session,
        name="New Project",
        description="Test",
        library=library,
        auto_assign_reference=False,
    )

    # Should NOT have reference assigned
    assert new_proj.general_corpus_id is None


# ============================================================================
# delete_project() guard tests
# ============================================================================


def test_delete_project_blocks_reference_corpus_deletion(project_service, session, library):
    """delete_project() raises error when attempting to delete reference corpus."""
    # Create reference corpus
    ref = DictProject(
        library_id=library.library_id,
        name="Reference Corpus",
        is_general_corpus=1,
    )
    session.add(ref)
    session.commit()
    session.refresh(ref)

    # Attempt to delete reference corpus → should raise
    with pytest.raises(ReferenceCorpusReadonlyError) as exc_info:
        project_service.delete_project(session, ref.project_id)

    assert "Cannot delete reference corpus" in str(exc_info.value)
    assert "Reference Corpus" in str(exc_info.value)

    # Verify project still exists
    session.expire_all()
    assert session.get(DictProject, ref.project_id) is not None


def test_delete_project_allows_normal_project_deletion(project_service, session, library):
    """delete_project() allows deletion of normal projects."""
    # Create normal project
    proj = DictProject(
        library_id=library.library_id,
        name="Normal Project",
        is_general_corpus=0,
    )
    session.add(proj)
    session.commit()
    session.refresh(proj)

    # Delete should succeed
    report = project_service.delete_project(session, proj.project_id)

    assert report.success
    assert report.project_name == "Normal Project"

    # Verify project deleted
    session.expire_all()
    assert session.get(DictProject, proj.project_id) is None
