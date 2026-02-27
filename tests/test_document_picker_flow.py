"""Document picker search/paging and Sentences filter wiring tests."""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QDialog
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.infra.sa_models import DictProject, Library, SourceCorpus, SourceDocument
from app.services.document_service import DocumentService
from app.ui.sentences_view import SentencesView


@pytest.fixture
def doc_picker_engine():
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


def _seed_project_docs(session: Session, count: int = 140) -> int:
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
                file_path=f"/tmp/doc_{i:04d}.txt",
                file_name=f"title_{count - i:04d}",
                file_ext=".txt",
                file_size_bytes=100 + i,
                sha256=f"sha_{i:06d}",
                imported_at=f"2026-01-01T00:00:00.{i:06d}Z",
                status="processed",
                sentence_count=i % 11,
                token_count=i % 17,
                tag="tag_a" if i % 9 == 0 else "tag_b",
            )
        )
    session.add_all(docs)
    session.commit()
    return int(project.project_id)


def test_document_picker_search_paged(doc_picker_engine):
    svc = DocumentService()
    with Session(doc_picker_engine) as session:
        project_id = _seed_project_docs(session, count=140)
        total = svc.get_project_documents_total_count(session, project_id, search_query="tag_a")
        page = svc.fetch_project_documents_page(
            session,
            project_id,
            search_query="tag_a",
            limit=25,
            offset=0,
        )

    assert total > 0
    assert len(page) <= 25
    assert all("tag_a" in (dto.tag or "") for dto in page)


def test_document_picker_tag_prefix_contains_mode(doc_picker_engine):
    svc = DocumentService()
    with Session(doc_picker_engine) as session:
        project_id = _seed_project_docs(session, count=40)
        docs = (
            session.query(SourceDocument)
            .join(SourceCorpus, SourceDocument.corpus_id == SourceCorpus.corpus_id)
            .filter(SourceCorpus.project_id == project_id)
            .order_by(SourceDocument.doc_id.asc())
            .limit(3)
            .all()
        )
        docs[0].tag = "wiki_alpha"
        docs[1].tag = "alpha_wiki_beta"
        docs[2].tag = "other"
        session.commit()

        total = svc.get_project_documents_total_count(session, project_id, search_query="tag:wiki")
        page = svc.fetch_project_documents_page(
            session,
            project_id,
            search_query="tag:wiki",
            sort_by="file_name",
            sort_dir="asc",
            limit=25,
            offset=0,
        )

    assert total == 2
    assert len(page) == 2
    assert all("wiki" in (dto.tag or "") for dto in page)


def test_document_picker_search_dedupes_filename_and_tag_match(doc_picker_engine):
    svc = DocumentService()
    with Session(doc_picker_engine) as session:
        project_id = _seed_project_docs(session, count=30)
        docs = (
            session.query(SourceDocument)
            .join(SourceCorpus, SourceDocument.corpus_id == SourceCorpus.corpus_id)
            .filter(SourceCorpus.project_id == project_id)
            .order_by(SourceDocument.doc_id.asc())
            .limit(3)
            .all()
        )
        docs[0].file_name = "wiki_primary_doc"
        docs[0].tag = "wiki"
        docs[1].file_name = "wiki_secondary_doc"
        docs[1].tag = "other"
        docs[2].file_name = "control_doc"
        docs[2].tag = "other"
        session.commit()

        total = svc.get_project_documents_total_count(session, project_id, search_query="wiki")
        page = svc.fetch_project_documents_page(
            session,
            project_id,
            search_query="wiki",
            sort_by="file_name",
            sort_dir="asc",
            limit=25,
            offset=0,
        )

    assert total == 2
    assert len(page) == 2
    assert [dto.file_name for dto in page] == ["wiki_primary_doc", "wiki_secondary_doc"]


def test_sentences_view_applies_selected_document_filter(monkeypatch, qtbot):
    calls = []

    monkeypatch.setattr(
        "app.ui.sentences_view.DBService.get_instance",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(
        SentencesView,
        "_reload",
        lambda self: calls.append(self._doc_filter),
    )

    class _FakeDialog:
        DialogCode = QDialog.DialogCode

        def __init__(self, *args, **kwargs):
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

        def selected_document(self):
            return 321, "Doc 321"

    monkeypatch.setattr("app.ui.sentences_view.DocumentPickerDialog", _FakeDialog)

    view = SentencesView(project_id=1)
    qtbot.addWidget(view)
    calls.clear()

    view._on_pick_document()
    assert view._doc_filter == 321
    assert view.doc_filter_label.text() == "Doc 321"
    assert calls and calls[-1] == 321

    view._on_clear_filters()
    assert view._doc_filter is None
    assert view.doc_filter_label.text() == "All Documents"
