"""Tests for ProjectDashboard real metrics loading (PATCH-02).

Tests that ProjectDashboard loads REAL metrics (not hardcoded zeros)
for reference corpus and regular projects.
"""
import pytest
import tempfile
import sqlite3
from pathlib import Path

from app.infra.sa_models import (
    Library, DictProject, SourceCorpus, SourceDocument,
    Lemma, LemmaProjectStat, Ngram, NgramProjectStat
)
from app.services.project_service import ProjectService
from app.services.db_service import DBService


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
# get_project_stats() tests
# ============================================================================


def test_get_project_stats_empty_project(project_service, session, library):
    """get_project_stats() returns zeros for empty project."""
    # Create empty project
    proj = DictProject(
        library_id=library.library_id,
        name="Empty Project",
        is_general_corpus=0,
    )
    session.add(proj)
    session.commit()
    session.refresh(proj)

    # Get stats
    stats = project_service.get_project_stats(session, proj.project_id)

    assert stats["total_docs"] == 0
    assert stats["processed_docs"] == 0
    assert stats["total_lemmas"] == 0
    assert stats["total_ngrams"] == 0


def test_get_project_stats_with_documents(project_service, session, library):
    """get_project_stats() returns correct document counts."""
    # Create project
    proj = DictProject(
        library_id=library.library_id,
        name="Test Project",
        is_general_corpus=0,
    )
    session.add(proj)
    session.commit()
    session.refresh(proj)

    # Create corpus
    corpus = SourceCorpus(
        project_id=proj.project_id,
        name="Main Corpus",
        description="Test",
    )
    session.add(corpus)
    session.commit()
    session.refresh(corpus)

    # Create documents
    doc1 = SourceDocument(
        corpus_id=corpus.corpus_id,
        file_name="doc1.txt",
        file_path="/fake/doc1.txt",
        file_ext=".txt",
        file_size_bytes=100,
        sha256="hash1",
        status="imported",
    )
    doc2 = SourceDocument(
        corpus_id=corpus.corpus_id,
        file_name="doc2.txt",
        file_path="/fake/doc2.txt",
        file_ext=".txt",
        file_size_bytes=100,
        sha256="hash2",
        status="processed",
    )
    doc3 = SourceDocument(
        corpus_id=corpus.corpus_id,
        file_name="doc3.txt",
        file_path="/fake/doc3.txt",
        file_ext=".txt",
        file_size_bytes=100,
        sha256="hash3",
        status="processed",
    )
    session.add_all([doc1, doc2, doc3])
    session.commit()

    # Get stats
    stats = project_service.get_project_stats(session, proj.project_id)

    assert stats["total_docs"] == 3
    assert stats["processed_docs"] == 2  # Only doc2 and doc3 are processed


def test_get_project_stats_with_lemmas_and_ngrams(project_service, session, library):
    """get_project_stats() returns correct lemma and ngram counts."""
    # Create project
    proj = DictProject(
        library_id=library.library_id,
        name="Test Project",
        is_general_corpus=0,
    )
    session.add(proj)
    session.commit()
    session.refresh(proj)

    # Create lemmas (just lemma records, stats separate)
    lemma1 = Lemma(
        project_id=proj.project_id,
        lemma_text="test1",
        pos="NOUN",
    )
    lemma2 = Lemma(
        project_id=proj.project_id,
        lemma_text="test2",
        pos="VERB",
    )
    session.add_all([lemma1, lemma2])
    session.commit()
    session.refresh(lemma1)
    session.refresh(lemma2)

    # Create lemma stats
    lemma_stat1 = LemmaProjectStat(
        project_id=proj.project_id,
        lemma_id=lemma1.lemma_id,
        freq_abs=10,
        doc_freq=5,
    )
    lemma_stat2 = LemmaProjectStat(
        project_id=proj.project_id,
        lemma_id=lemma2.lemma_id,
        freq_abs=5,
        doc_freq=3,
    )
    session.add_all([lemma_stat1, lemma_stat2])
    session.commit()

    # Create ngrams
    ngram1 = Ngram(
        project_id=proj.project_id,
        surface_text="test ngram",
        n=2,
    )
    session.add(ngram1)
    session.commit()
    session.refresh(ngram1)

    # Create ngram stat
    ngram_stat1 = NgramProjectStat(
        project_id=proj.project_id,
        ngram_id=ngram1.ngram_id,
        freq_abs=3,
        doc_freq=2,
    )
    session.add(ngram_stat1)
    session.commit()

    # Get stats
    stats = project_service.get_project_stats(session, proj.project_id)

    assert stats["total_lemmas"] == 2
    assert stats["total_ngrams"] == 1


def test_get_project_stats_reference_corpus(project_service, session, library):
    """get_project_stats() works correctly for reference corpus projects."""
    # Create reference corpus project
    ref_proj = DictProject(
        library_id=library.library_id,
        name="Reference Corpus",
        is_general_corpus=1,
    )
    session.add(ref_proj)
    session.commit()
    session.refresh(ref_proj)

    # Create corpus
    corpus = SourceCorpus(
        project_id=ref_proj.project_id,
        name="Main Corpus",
        description="Test",
    )
    session.add(corpus)
    session.commit()
    session.refresh(corpus)

    # Create documents
    for i in range(5):
        doc = SourceDocument(
            corpus_id=corpus.corpus_id,
            file_name=f"doc{i}.txt",
            file_path=f"/fake/doc{i}.txt",
            file_ext=".txt",
            file_size_bytes=100,
            sha256=f"hash{i}",
            status="processed",
        )
        session.add(doc)
    session.commit()

    # Get stats
    stats = project_service.get_project_stats(session, ref_proj.project_id)

    assert stats["total_docs"] == 5
    assert stats["processed_docs"] == 5


# ============================================================================
# ProjectDashboard integration test (mock-based)
# ============================================================================


def test_project_dashboard_loads_real_metrics(project_service, session, library):
    """ProjectDashboard should load REAL metrics, not zeros."""
    # Create project with data
    proj = DictProject(
        library_id=library.library_id,
        name="Test Project",
        is_general_corpus=0,
    )
    session.add(proj)
    session.commit()
    session.refresh(proj)

    # Create corpus
    corpus = SourceCorpus(
        project_id=proj.project_id,
        name="Main Corpus",
        description="Test",
    )
    session.add(corpus)
    session.commit()
    session.refresh(corpus)

    # Create documents
    for i in range(10):
        doc = SourceDocument(
            corpus_id=corpus.corpus_id,
            file_name=f"doc{i}.txt",
            file_path=f"/fake/doc{i}.txt",
            file_ext=".txt",
            file_size_bytes=100,
            sha256=f"hash{i}",
            status="processed" if i < 7 else "imported",
        )
        session.add(doc)
    session.commit()

    # Create lemmas with stats
    for i in range(50):
        lemma = Lemma(
            project_id=proj.project_id,
            lemma_text=f"lemma{i}",
            pos="NOUN",
        )
        session.add(lemma)
        session.flush()  # Get lemma_id

        lemma_stat = LemmaProjectStat(
            project_id=proj.project_id,
            lemma_id=lemma.lemma_id,
            freq_abs=1,
            doc_freq=1,
        )
        session.add(lemma_stat)
    session.commit()

    # Simulate ProjectDashboard.load_projects() logic
    projects = project_service.list_projects(session)
    assert len(projects) == 1

    # Get stats for the project (this is what ProjectDashboard does now)
    project_metrics = project_service.get_project_stats(session, projects[0].project_id)

    # Verify REAL metrics are loaded (not zeros)
    assert project_metrics["total_docs"] == 10
    assert project_metrics["processed_docs"] == 7
    assert project_metrics["total_lemmas"] == 50
    assert project_metrics["total_ngrams"] == 0  # No ngrams created
