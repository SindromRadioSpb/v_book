"""Documents global SQL pagination/sort/search tests for large datasets."""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.infra.sa_models import DictProject, Library, SourceCorpus, SourceDocument
from app.services.document_service import DocumentService
from app.ui.documents_view import DocumentsView


@pytest.fixture
def docs_engine():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        Library.__table__.create(engine, checkfirst=True)
        DictProject.__table__.create(engine, checkfirst=True)
        SourceCorpus.__table__.create(engine, checkfirst=True)
        SourceDocument.__table__.create(engine, checkfirst=True)
        yield engine
    finally:
        engine.dispose()
        Path(db_path).unlink(missing_ok=True)


def _seed_docs(session: Session, count: int = 100) -> int:
    lib = Library(name="L")
    session.add(lib)
    session.flush()
    project = DictProject(library_id=lib.library_id, name="P", src_lang="he", tgt_lang="ru")
    session.add(project)
    session.flush()
    corpus = SourceCorpus(project_id=project.project_id, name="C")
    session.add(corpus)
    session.flush()

    docs = []
    for i in range(count):
        docs.append(
            SourceDocument(
                corpus_id=corpus.corpus_id,
                file_path=f"/tmp/{i:04d}.txt",
                file_name=f"title_{count - i:04d}",
                file_ext=".txt",
                file_size_bytes=1000 + i,
                sha256=f"sha_{i:06d}",
                imported_at=f"2026-01-01T00:00:00.{i:06d}Z",
                status="processed",
                sentence_count=i % 11,
                token_count=i % 101,
                tag="grammar" if (i % 17 == 0) else "other",
                level="aleph" if (i % 3 == 0) else "bet",
                topic="physics" if (i % 9 == 0) else "general",
            )
        )
    session.add_all(docs)
    session.commit()
    return int(corpus.corpus_id)


def test_documents_global_sorting_applies_before_pagination(docs_engine):
    svc = DocumentService()
    with Session(docs_engine) as session:
        corpus_id = _seed_docs(session, count=100)
        all_sorted = svc.list_documents(
            session,
            corpus_id,
            sort_by="file_name",
            sort_dir="asc",
        )
        expected_page_2 = [d.file_name for d in all_sorted[20:40]]
        page_2 = svc.fetch_documents_page(
            session,
            corpus_id,
            sort_by="file_name",
            sort_dir="asc",
            limit=20,
            offset=20,
        )
        got_page_2 = [d.file_name for d in page_2]
        assert got_page_2 == expected_page_2


def test_documents_search_title_is_global(docs_engine):
    svc = DocumentService()
    with Session(docs_engine) as session:
        corpus_id = _seed_docs(session, count=90)
        # Inject matches outside first 25 inserted rows.
        target_a = (
            session.query(SourceDocument)
            .filter(SourceDocument.corpus_id == corpus_id)
            .offset(55)
            .first()
        )
        target_b = (
            session.query(SourceDocument)
            .filter(SourceDocument.corpus_id == corpus_id)
            .offset(70)
            .first()
        )
        target_a.file_name = "needle_alpha.txt"
        target_b.file_name = "needle_beta.txt"
        session.commit()

        total = svc.get_documents_total_count(session, corpus_id, title_search="needle")
        page = svc.fetch_documents_page(
            session,
            corpus_id,
            title_search="needle",
            sort_by="file_name",
            sort_dir="asc",
            limit=25,
            offset=0,
        )
        names = [d.file_name for d in page]
        assert total == 2
        assert names == ["needle_alpha.txt", "needle_beta.txt"]


def test_documents_tag_filter_is_global(docs_engine):
    svc = DocumentService()
    with Session(docs_engine) as session:
        corpus_id = _seed_docs(session, count=120)
        total = svc.get_documents_total_count(session, corpus_id, tag_filter="grammar")
        page = svc.fetch_documents_page(
            session,
            corpus_id,
            tag_filter="grammar",
            sort_by="doc_id",
            sort_dir="asc",
            limit=25,
            offset=0,
        )
        assert total > 0
        assert len(page) <= 25
        assert all((d.tag or "").lower().find("grammar") >= 0 for d in page)


def test_documents_request_id_cancels_stale_updates(monkeypatch, qtbot):
    monkeypatch.setattr(
        "app.ui.documents_view.DBService.get_instance",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(
        DocumentsView,
        "load_corpus",
        lambda self: setattr(self, "corpus_id", 1),
    )
    monkeypatch.setattr(
        DocumentsView,
        "reload_documents",
        lambda self, reset_page=False: None,
    )
    monkeypatch.setattr(
        DocumentsView,
        "start_nlp_engine_readiness_check",
        lambda self: None,
    )

    view = DocumentsView(project_id=1)
    qtbot.addWidget(view)
    rendered = []
    monkeypatch.setattr(view, "_render_documents_rows", lambda rows: rendered.append(list(rows)))

    view._active_request_id = 2
    view.current_page = 1
    view.page_size = 25

    view.on_documents_page_loaded(1, 100, [SimpleNamespace(doc_id=10)])
    assert rendered == []

    view.on_documents_page_loaded(2, 100, [SimpleNamespace(doc_id=11)])
    assert len(rendered) == 1
    assert rendered[0][0].doc_id == 11
