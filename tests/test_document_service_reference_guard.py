"""Tests for document service reference corpus guards (PATCH-05 logic).

Tests IngestService blocks document operations on reference corpus:
- import_document() raises ReferenceCorpusReadonlyError
- delete_document() raises ReferenceCorpusReadonlyError
"""
import pytest
import tempfile
import sqlite3
from pathlib import Path

from app.infra.sa_models import Library, DictProject, SourceCorpus, SourceDocument
from app.services.ingest_service import IngestService
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
def ingest_service(temp_db):
    """Create IngestService instance (requires temp_db to initialize DBService)."""
    return IngestService()


@pytest.fixture
def library(session):
    """Create default library."""
    lib = Library(name="Test Library")
    session.add(lib)
    session.commit()
    session.refresh(lib)
    return lib


@pytest.fixture
def test_file(tmp_path):
    """Create a temporary test file."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("Test document content for testing", encoding="utf-8")
    return test_file


# ============================================================================
# import_document() guard tests
# ============================================================================


def test_import_document_blocks_reference_corpus(
    ingest_service, session, library, test_file
):
    """import_document() raises error when importing to reference corpus."""
    # Create reference corpus project
    ref_proj = DictProject(
        library_id=library.library_id,
        name="Reference Corpus",
        is_general_corpus=1,
    )
    session.add(ref_proj)
    session.commit()
    session.refresh(ref_proj)

    # Create corpus for reference project
    ref_corpus = SourceCorpus(
        project_id=ref_proj.project_id,
        name="Main Corpus",
        description="Test",
    )
    session.add(ref_corpus)
    session.commit()
    session.refresh(ref_corpus)

    # Attempt to import document → should raise
    with pytest.raises(ReferenceCorpusReadonlyError) as exc_info:
        ingest_service.import_document(
            session,
            corpus_id=ref_corpus.corpus_id,
            file_path=test_file,
            use_ocr=False,
        )

    assert "Cannot add documents to reference corpus" in str(exc_info.value)
    assert "Reference Corpus" in str(exc_info.value)

    # Verify no document was added
    from sqlalchemy import select
    stmt = select(SourceDocument).where(SourceDocument.corpus_id == ref_corpus.corpus_id)
    docs = session.execute(stmt).scalars().all()
    assert len(docs) == 0


def test_import_document_allows_normal_project(
    ingest_service, session, library, test_file
):
    """import_document() allows importing to normal projects."""
    # Create normal project
    proj = DictProject(
        library_id=library.library_id,
        name="Normal Project",
        is_general_corpus=0,
    )
    session.add(proj)
    session.commit()
    session.refresh(proj)

    # Create corpus for normal project
    corpus = SourceCorpus(
        project_id=proj.project_id,
        name="Main Corpus",
        description="Test",
    )
    session.add(corpus)
    session.commit()
    session.refresh(corpus)

    # Import should succeed
    doc = ingest_service.import_document(
        session,
        corpus_id=corpus.corpus_id,
        file_path=test_file,
        use_ocr=False,
    )

    assert doc is not None
    assert doc.corpus_id == corpus.corpus_id
    assert doc.status == "imported"


# ============================================================================
# delete_document() guard tests
# ============================================================================


def test_delete_document_blocks_reference_corpus(
    ingest_service, session, library
):
    """delete_document() raises error when deleting from reference corpus."""
    # Create reference corpus project
    ref_proj = DictProject(
        library_id=library.library_id,
        name="Reference Corpus",
        is_general_corpus=1,
    )
    session.add(ref_proj)
    session.commit()
    session.refresh(ref_proj)

    # Create corpus for reference project
    ref_corpus = SourceCorpus(
        project_id=ref_proj.project_id,
        name="Main Corpus",
        description="Test",
    )
    session.add(ref_corpus)
    session.commit()
    session.refresh(ref_corpus)

    # Create document (manually, bypassing import guard)
    doc = SourceDocument(
        corpus_id=ref_corpus.corpus_id,
        file_name="test.txt",
        file_path="/fake/path/test.txt",
        file_ext=".txt",
        file_size_bytes=100,
        sha256="fake_hash",
        status="imported",
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)

    # Attempt to delete document → should raise
    with pytest.raises(ReferenceCorpusReadonlyError) as exc_info:
        ingest_service.delete_document(session, doc.doc_id)

    assert "Cannot delete documents from reference corpus" in str(exc_info.value)
    assert "Reference Corpus" in str(exc_info.value)

    # Verify document still exists
    session.expire_all()
    assert session.get(SourceDocument, doc.doc_id) is not None


def test_delete_document_allows_normal_project(
    ingest_service, session, library
):
    """delete_document() allows deleting from normal projects."""
    # Create normal project
    proj = DictProject(
        library_id=library.library_id,
        name="Normal Project",
        is_general_corpus=0,
    )
    session.add(proj)
    session.commit()
    session.refresh(proj)

    # Create corpus for normal project
    corpus = SourceCorpus(
        project_id=proj.project_id,
        name="Main Corpus",
        description="Test",
    )
    session.add(corpus)
    session.commit()
    session.refresh(corpus)

    # Create document
    doc = SourceDocument(
        corpus_id=corpus.corpus_id,
        file_name="test.txt",
        file_path="/fake/path/test.txt",
        file_ext=".txt",
        file_size_bytes=100,
        sha256="fake_hash",
        status="imported",
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)
    doc_id = int(doc.doc_id)

    # Delete should succeed
    result = ingest_service.delete_document(session, doc_id)

    assert result is True

    # Verify document deleted
    session.expire_all()
    assert session.get(SourceDocument, doc_id) is None
