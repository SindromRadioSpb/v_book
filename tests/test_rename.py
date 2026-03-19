"""Smoke tests for project and document rename functionality."""

import pytest
import sqlite3
from pathlib import Path
from sqlalchemy import select

from app.services.project_service import ProjectService
from app.services.ingest_service import IngestService
from app.infra.sa_models import DictProject, Library, SourceCorpus, SourceDocument
from app.services.db_service import DBService


@pytest.fixture
def db_service(tmp_path):
    """Database service fixture."""
    db_path = tmp_path / "test_rename.db"

    # Apply migrations
    conn = sqlite3.connect(str(db_path))
    try:
        migration_dir = Path(__file__).parent.parent / "app" / "infra" / "migrations"
        for migration_file in sorted(migration_dir.glob("*.sql")):
            with open(migration_file, "r", encoding="utf-8") as f:
                conn.executescript(f.read())
        conn.commit()
    finally:
        conn.close()

    # Initialize DBService
    DBService.initialize(str(db_path))

    yield DBService.get_instance()

    # Cleanup
    DBService.shutdown()
    DBService._instance = None


@pytest.fixture
def project_service(db_service):
    """Project service fixture."""
    return ProjectService()


@pytest.fixture
def ingest_service(db_service):
    """Ingest service fixture."""
    return IngestService()


@pytest.fixture
def test_project(db_service, project_service):
    """Create a test project."""
    with db_service.get_session() as session:
        library = project_service.get_or_create_default_library(session)
        project = DictProject(
            library_id=library.library_id,
            name="Test Rename Project",
            description="For rename tests",
        )
        session.add(project)
        session.commit()
        session.refresh(project)

        # Create corpus
        corpus = SourceCorpus(
            project_id=project.project_id,
            name="Test Corpus",
        )
        session.add(corpus)
        session.commit()

        yield project.project_id

        # Cleanup (if not already deleted in test)
        try:
            project = session.get(DictProject, project.project_id)
            if project:
                session.delete(project)
                session.commit()
        except Exception:
            pass


@pytest.fixture
def test_document(db_service, test_project):
    """Create a test document."""
    with db_service.get_session() as session:
        # Get corpus
        corpus = session.execute(
            select(SourceCorpus).where(SourceCorpus.project_id == test_project)
        ).scalar_one()

        # Create document
        doc = SourceDocument(
            corpus_id=corpus.corpus_id,
            file_path="/tmp/test.txt",
            file_name="test.txt",
            file_ext=".txt",
            file_size_bytes=100,
            sha256="test_hash_123",
            status="imported",
        )
        session.add(doc)
        session.commit()
        session.refresh(doc)

        yield doc.doc_id

        # Cleanup
        try:
            doc = session.get(SourceDocument, doc.doc_id)
            if doc:
                session.delete(doc)
                session.commit()
        except Exception:
            pass


# ============================================================================
# Project Rename Tests
# ============================================================================


def test_project_rename_success(db_service, project_service, test_project):
    """Test successful project rename."""
    with db_service.get_session() as session:
        # Rename
        updated = project_service.rename_project(session, test_project, "New Project Name")

        assert updated.name == "New Project Name"
        assert updated.project_id == test_project

        # Verify in DB
        project = session.get(DictProject, test_project)
        assert project.name == "New Project Name"


def test_project_rename_empty_name(db_service, project_service, test_project):
    """Test that empty name is rejected."""
    with db_service.get_session() as session:
        with pytest.raises(ValueError, match="cannot be empty"):
            project_service.rename_project(session, test_project, "")


def test_project_rename_whitespace_only(db_service, project_service, test_project):
    """Test that whitespace-only name is rejected."""
    with db_service.get_session() as session:
        with pytest.raises(ValueError, match="cannot be empty"):
            project_service.rename_project(session, test_project, "   ")


def test_project_rename_too_long(db_service, project_service, test_project):
    """Test that name exceeding 255 chars is rejected."""
    with db_service.get_session() as session:
        long_name = "A" * 256
        with pytest.raises(ValueError, match="cannot exceed 255 characters"):
            project_service.rename_project(session, test_project, long_name)


def test_project_rename_forbidden_chars(db_service, project_service, test_project):
    """Test that forbidden characters are rejected."""
    forbidden = ["/", "\\", ":", "*", "?", '"', "<", ">", "|"]

    with db_service.get_session() as session:
        for char in forbidden:
            with pytest.raises(ValueError, match="forbidden characters"):
                project_service.rename_project(session, test_project, f"Bad{char}Name")


def test_project_rename_duplicate_name(db_service, project_service, test_project):
    """Test that duplicate name in same library is rejected."""
    with db_service.get_session() as session:
        # Get project's library
        project = session.get(DictProject, test_project)
        library_id = project.library_id

        # Create another project in same library
        other_project = DictProject(
            library_id=library_id,
            name="Existing Project",
            description="Already exists",
        )
        session.add(other_project)
        session.commit()

        try:
            # Try to rename test_project to same name
            with pytest.raises(ValueError, match="already exists"):
                project_service.rename_project(session, test_project, "Existing Project")
        finally:
            # Cleanup
            session.delete(other_project)
            session.commit()


def test_project_rename_unchanged_name(db_service, project_service, test_project):
    """Test that renaming to same name is a no-op."""
    with db_service.get_session() as session:
        project = session.get(DictProject, test_project)
        original_name = project.name

        # Rename to same name
        updated = project_service.rename_project(session, test_project, original_name)

        assert updated.name == original_name


# ============================================================================
# Document Rename Tests
# ============================================================================


def test_document_rename_success(db_service, ingest_service, test_document):
    """Test successful document rename."""
    with db_service.get_session() as session:
        # Rename (keep same extension)
        updated = ingest_service.rename_document(session, test_document, "renamed.txt")

        assert updated.file_name == "renamed.txt"
        assert updated.doc_id == test_document

        # Verify in DB
        doc = session.get(SourceDocument, test_document)
        assert doc.file_name == "renamed.txt"


def test_document_rename_empty_name(db_service, ingest_service, test_document):
    """Test that empty name is rejected."""
    with db_service.get_session() as session:
        with pytest.raises(ValueError, match="cannot be empty"):
            ingest_service.rename_document(session, test_document, "")


def test_document_rename_whitespace_only(db_service, ingest_service, test_document):
    """Test that whitespace-only name is rejected."""
    with db_service.get_session() as session:
        with pytest.raises(ValueError, match="cannot be empty"):
            ingest_service.rename_document(session, test_document, "   ")


def test_document_rename_too_long(db_service, ingest_service, test_document):
    """Test that name exceeding 255 chars is rejected."""
    with db_service.get_session() as session:
        long_name = "A" * 256 + ".txt"
        with pytest.raises(ValueError, match="cannot exceed 255 characters"):
            ingest_service.rename_document(session, test_document, long_name)


def test_document_rename_forbidden_chars(db_service, ingest_service, test_document):
    """Test that forbidden characters are rejected."""
    forbidden = ["/", "\\", ":", "*", "?", '"', "<", ">", "|"]

    with db_service.get_session() as session:
        for char in forbidden:
            with pytest.raises(ValueError, match="forbidden characters"):
                ingest_service.rename_document(session, test_document, f"bad{char}name.txt")


def test_document_rename_extension_mismatch(db_service, ingest_service, test_document):
    """Test that changing extension is rejected."""
    with db_service.get_session() as session:
        # Try to change .txt to .docx
        with pytest.raises(ValueError, match="extension must remain"):
            ingest_service.rename_document(session, test_document, "renamed.docx")


def test_document_rename_no_extension(db_service, ingest_service, test_document):
    """Test that removing extension is rejected."""
    with db_service.get_session() as session:
        with pytest.raises(ValueError, match="extension must remain"):
            ingest_service.rename_document(session, test_document, "renamed")


def test_document_rename_unchanged_name(db_service, ingest_service, test_document):
    """Test that renaming to same name is a no-op."""
    with db_service.get_session() as session:
        doc = session.get(SourceDocument, test_document)
        original_name = doc.file_name

        # Rename to same name
        updated = ingest_service.rename_document(session, test_document, original_name)

        assert updated.file_name == original_name


def test_document_rename_case_change(db_service, ingest_service, test_document):
    """Test that changing case of extension is accepted."""
    with db_service.get_session() as session:
        # Change .txt to .TXT (case-insensitive match)
        updated = ingest_service.rename_document(session, test_document, "renamed.TXT")

        assert updated.file_name == "renamed.TXT"
