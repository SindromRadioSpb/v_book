"""Tests for PERF-SCALE PATCH-D: document_name_fts FTS5 + picker search routing.

Covers:
- FTS5 table + triggers created by migration 027 / fts_manager health check
- FTS5 search path in DocumentService (picker_page_search via MATCH)
- LIKE fallback path when FTS5 table is absent
- FTS5 escape function handles special characters safely
- Sync triggers keep FTS index consistent after INSERT / UPDATE / DELETE
- Existing LIKE-based picker tests still pass without FTS5 table
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.infra.fts_manager import (
    DOCUMENT_NAME_FTS_DDL,
    DOCUMENT_NAME_FTS_TRIGGERS,
    ensure_document_name_fts_health,
)
from app.infra.sa_models import DictProject, Library, SourceCorpus, SourceDocument
from app.services.document_service import DocumentService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_engine(db_path: str):
    engine = create_engine(f"sqlite:///{db_path}")
    Library.__table__.create(engine, checkfirst=True)
    DictProject.__table__.create(engine, checkfirst=True)
    SourceCorpus.__table__.create(engine, checkfirst=True)
    SourceDocument.__table__.create(engine, checkfirst=True)
    return engine


@pytest.fixture
def plain_engine():
    """Engine without FTS5 table — exercises LIKE fallback path."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    engine = _make_engine(db_path)
    try:
        yield engine
    finally:
        engine.dispose()
        Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def fts_engine():
    """Engine with document_name_fts FTS5 table — exercises fast FTS5 path."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    engine = _make_engine(db_path)
    # Create FTS5 table + triggers via fts_manager
    raw = engine.raw_connection()
    try:
        ensure_document_name_fts_health(raw, schema="main", rebuild=True)
    finally:
        raw.close()
    try:
        yield engine
    finally:
        engine.dispose()
        Path(db_path).unlink(missing_ok=True)


def _seed(session: Session, count: int = 30) -> tuple[int, list[int]]:
    """Seed project with documents, return (project_id, [doc_ids])."""
    lib = Library(name="TestLib")
    session.add(lib)
    session.flush()
    project = DictProject(
        library_id=lib.library_id, name="TestProject", src_lang="he", tgt_lang="ru"
    )
    session.add(project)
    session.flush()
    corpus = SourceCorpus(project_id=project.project_id, name="TestCorpus")
    session.add(corpus)
    session.flush()

    docs = []
    for i in range(count):
        docs.append(
            SourceDocument(
                corpus_id=corpus.corpus_id,
                file_path=f"/wiki/doc_{i:04d}",
                file_name=f"מאמר_{i:04d}" if i % 3 != 0 else f"wiki_article_{i:04d}",
                file_ext=".wiki",
                file_size_bytes=100 + i,
                sha256=f"sha_{i:08d}",
                imported_at=f"2026-01-{(i % 28) + 1:02d}T00:00:00Z",
                status="processed",
                tag="wiki" if i % 5 == 0 else "regular",
            )
        )
    session.add_all(docs)
    session.commit()
    return int(project.project_id), [int(d.doc_id) for d in docs]


# ---------------------------------------------------------------------------
# FTS5 escape function
# ---------------------------------------------------------------------------


def test_fts5_escape_plain_term():
    result = DocumentService._fts5_escape_term("מתמטיקה")
    assert result == '"מתמטיקה"*'


def test_fts5_escape_multi_word():
    result = DocumentService._fts5_escape_term("תל אביב")
    assert result == '"תל אביב"*'


def test_fts5_escape_embedded_quote():
    result = DocumentService._fts5_escape_term('foo "bar')
    assert result == '"foo ""bar"*'


def test_fts5_escape_empty_string():
    result = DocumentService._fts5_escape_term("")
    assert result == '""*'


# ---------------------------------------------------------------------------
# FTS5 table creation and health check
# ---------------------------------------------------------------------------


def test_ensure_document_name_fts_creates_table():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        conn = sqlite3.connect(db_path)
        # Create source_document so triggers don't fail
        conn.execute(
            "CREATE TABLE source_document "
            "(doc_id INTEGER PRIMARY KEY, file_name TEXT, corpus_id INTEGER)"
        )
        conn.commit()
        result = ensure_document_name_fts_health(conn, schema="main", rebuild=False)
        conn.close()

        assert result == {"document_name_fts": True}

        # Verify table and triggers exist
        conn2 = sqlite3.connect(db_path)
        tables = {
            r[0]
            for r in conn2.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        triggers = {
            r[0]
            for r in conn2.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()
        }
        conn2.close()

        assert "document_name_fts" in tables
        assert "trg_doc_name_fts_ai" in triggers
        assert "trg_doc_name_fts_au" in triggers
        assert "trg_doc_name_fts_ad" in triggers
    finally:
        Path(db_path).unlink(missing_ok=True)


def test_ensure_document_name_fts_idempotent():
    """Calling health check twice must not raise."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE source_document "
            "(doc_id INTEGER PRIMARY KEY, file_name TEXT, corpus_id INTEGER)"
        )
        conn.commit()
        result1 = ensure_document_name_fts_health(conn, schema="main", rebuild=False)
        result2 = ensure_document_name_fts_health(conn, schema="main", rebuild=False)
        conn.close()

        assert result1 == {"document_name_fts": True}
        assert result2 == {"document_name_fts": False}  # already existed, not re-created
    finally:
        Path(db_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# FTS5 sync triggers
# ---------------------------------------------------------------------------


def test_fts_trigger_insert_syncs(fts_engine):
    """Inserting a document updates the FTS index."""
    with Session(fts_engine) as session:
        project_id, _ = _seed(session, count=5)
        # Add a unique document after seeding
        corpus_id = session.execute(
            text("SELECT corpus_id FROM source_corpus WHERE project_id=:p"),
            {"p": project_id},
        ).scalar()
        new_doc = SourceDocument(
            corpus_id=corpus_id,
            file_path="/wiki/unique_test_fts",
            file_name="unique_fts_title_xyz",
            file_ext=".wiki",
            file_size_bytes=42,
            sha256="sha_unique_xyz",
            imported_at="2026-03-07T00:00:00Z",
            status="imported",
        )
        session.add(new_doc)
        session.commit()

        # FTS search must find it
        svc = DocumentService()
        results = svc.fetch_project_documents_page(
            session,
            project_id,
            search_query="unique_fts_title",
            limit=10,
            offset=0,
        )

    assert any(
        dto.file_name == "unique_fts_title_xyz" for dto in results
    ), f"FTS should have indexed new doc; got: {[d.file_name for d in results]}"


def test_fts_trigger_delete_syncs(fts_engine):
    """Deleting a document removes it from the FTS index."""
    with Session(fts_engine) as session:
        project_id, doc_ids = _seed(session, count=10)

        # Find first doc whose file_name starts with wiki_article
        doc = (
            session.query(SourceDocument)
            .filter(SourceDocument.file_name.like("wiki_article%"))
            .first()
        )
        assert doc is not None
        doc_id_to_delete = int(doc.doc_id)
        # Use raw DELETE to avoid SQLAlchemy cascade loading missing tables in test fixture.
        session.execute(
            text("DELETE FROM source_document WHERE doc_id = :doc_id"),
            {"doc_id": doc_id_to_delete},
        )
        session.commit()

        svc = DocumentService()
        results = svc.fetch_project_documents_page(
            session,
            project_id,
            search_query="wiki_article",
            limit=50,
            offset=0,
        )

    assert all(
        dto.doc_id != doc_id_to_delete for dto in results
    ), "Deleted doc must not appear in FTS results"


# ---------------------------------------------------------------------------
# DocumentService FTS5 path
# ---------------------------------------------------------------------------


def test_picker_fts_path_returns_matching_docs(fts_engine):
    """With FTS5 table present, file_name search returns correct documents."""
    svc = DocumentService()
    with Session(fts_engine) as session:
        project_id, _ = _seed(session, count=30)

        page = svc.fetch_project_documents_page(
            session,
            project_id,
            search_query="wiki_article",
            limit=50,
            offset=0,
        )
        total = svc.get_project_documents_total_count(
            session, project_id, search_query="wiki_article"
        )

    assert total > 0
    assert len(page) == total
    assert all("wiki_article" in dto.file_name for dto in page)


def test_picker_fts_path_also_falls_back_to_like_for_hebrew_titles(fts_engine):
    """Hebrew file names must remain searchable even if FTS tokenization is not enough."""
    svc = DocumentService()
    with Session(fts_engine) as session:
        project_id, _ = _seed(session, count=10)
        corpus_id = session.execute(
            text("SELECT corpus_id FROM source_corpus WHERE project_id=:p"),
            {"p": project_id},
        ).scalar()
        new_doc = SourceDocument(
            corpus_id=corpus_id,
            file_path="/wiki/axiom",
            file_name="אקסיומה",
            file_ext=".wiki",
            file_size_bytes=42,
            sha256="sha_axioma_001",
            imported_at="2026-03-08T00:00:00Z",
            status="imported",
        )
        session.add(new_doc)
        session.commit()

        page = svc.fetch_project_documents_page(
            session,
            project_id,
            search_query="אקסיומה",
            limit=20,
            offset=0,
        )
        total = svc.get_project_documents_total_count(
            session,
            project_id,
            search_query="אקסיומה",
        )

    assert total >= 1
    assert any(dto.file_name == "אקסיומה" for dto in page)


def test_picker_fts_is_available_returns_true(fts_engine):
    """_is_document_name_fts_available returns True when table exists."""
    svc = DocumentService()
    with Session(fts_engine) as session:
        assert svc._is_document_name_fts_available(session) is True


def test_picker_fts_is_available_returns_false_without_table(plain_engine):
    """_is_document_name_fts_available returns False when table is absent."""
    svc = DocumentService()
    with Session(plain_engine) as session:
        assert svc._is_document_name_fts_available(session) is False


def test_picker_fts_path_deduplicates_name_and_tag(fts_engine):
    """A document matching both FTS file_name and exact tag appears only once."""
    svc = DocumentService()
    with Session(fts_engine) as session:
        project_id, _ = _seed(session, count=10)

        # Update first doc to have both file_name containing query AND exact tag match
        corpus_id = session.execute(
            text("SELECT corpus_id FROM source_corpus WHERE project_id=:p"),
            {"p": project_id},
        ).scalar()
        doc = session.query(SourceDocument).filter_by(corpus_id=corpus_id).first()
        doc.file_name = "overlap_query_test"
        doc.tag = "overlap_query_test"
        session.commit()

        page = svc.fetch_project_documents_page(
            session,
            project_id,
            search_query="overlap_query_test",
            limit=50,
            offset=0,
        )

    ids = [dto.doc_id for dto in page]
    assert len(ids) == len(set(ids)), "UNION must not return duplicate doc_ids"


# ---------------------------------------------------------------------------
# LIKE fallback path (no FTS5 table)
# ---------------------------------------------------------------------------


def test_picker_like_fallback_returns_results(plain_engine):
    """Without FTS5 table, DocumentService falls back to LIKE search correctly."""
    svc = DocumentService()
    with Session(plain_engine) as session:
        project_id, _ = _seed(session, count=30)

        page = svc.fetch_project_documents_page(
            session,
            project_id,
            search_query="wiki_article",
            limit=50,
            offset=0,
        )
        total = svc.get_project_documents_total_count(
            session, project_id, search_query="wiki_article"
        )

    assert total > 0
    assert len(page) == total
    assert all("wiki_article" in dto.file_name for dto in page)


def test_picker_tag_prefix_mode_unchanged(fts_engine):
    """tag: prefix mode always uses LIKE on tag column regardless of FTS availability."""
    svc = DocumentService()
    with Session(fts_engine) as session:
        project_id, _ = _seed(session, count=30)

        page = svc.fetch_project_documents_page(
            session,
            project_id,
            search_query="tag:wiki",
            limit=50,
            offset=0,
        )
        total = svc.get_project_documents_total_count(session, project_id, search_query="tag:wiki")

    assert total > 0
    assert len(page) == total
    assert all("wiki" in (dto.tag or "") for dto in page)
