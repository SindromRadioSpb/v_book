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
from app.ui.dialogs.document_picker_dialog import DocumentPickerDialog
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


def test_document_picker_explicit_filters_partial_tag_topic_and_level(doc_picker_engine):
    svc = DocumentService()
    with Session(doc_picker_engine) as session:
        project_id = _seed_project_docs(session, count=20)
        docs = (
            session.query(SourceDocument)
            .join(SourceCorpus, SourceDocument.corpus_id == SourceCorpus.corpus_id)
            .filter(SourceCorpus.project_id == project_id)
            .order_by(SourceDocument.doc_id.asc())
            .limit(4)
            .all()
        )
        docs[0].file_name = "baseline_math_ch01"
        docs[0].tag = "test_tag, tag 2"
        docs[0].topic = "mathematics"
        docs[0].level = "aleph"
        docs[1].file_name = "baseline_math_ch02"
        docs[1].tag = "test_tag"
        docs[1].topic = "mathematics advanced"
        docs[1].level = "bet"
        docs[2].file_name = "physics_intro"
        docs[2].tag = "physics"
        docs[2].topic = "science"
        docs[2].level = "aleph"
        session.commit()

        total = svc.get_project_documents_total_count(
            session,
            project_id,
            document_filter="baseline_math",
            tag_filter="tag",
            topic_filter="math",
            level_filter="aleph",
        )
        page = svc.fetch_project_documents_page(
            session,
            project_id,
            document_filter="baseline_math",
            tag_filter="tag",
            topic_filter="math",
            level_filter="aleph",
            sort_by="file_name",
            sort_dir="asc",
            limit=25,
            offset=0,
        )

    assert total == 1
    assert [dto.file_name for dto in page] == ["baseline_math_ch01"]


def test_document_picker_multiple_tags_support_any_and_all(doc_picker_engine):
    svc = DocumentService()
    with Session(doc_picker_engine) as session:
        project_id = _seed_project_docs(session, count=20)
        docs = (
            session.query(SourceDocument)
            .join(SourceCorpus, SourceDocument.corpus_id == SourceCorpus.corpus_id)
            .filter(SourceCorpus.project_id == project_id)
            .order_by(SourceDocument.doc_id.asc())
            .limit(3)
            .all()
        )
        docs[0].file_name = "doc_any_all"
        docs[0].tag = "test_tag, tag 2"
        docs[1].file_name = "doc_only_first"
        docs[1].tag = "test_tag"
        docs[2].file_name = "doc_only_second"
        docs[2].tag = "tag 2"
        session.commit()

        any_page = svc.fetch_project_documents_page(
            session,
            project_id,
            tag_filter="test_tag, tag 2",
            tag_match_mode="any",
            sort_by="file_name",
            sort_dir="asc",
            limit=25,
            offset=0,
        )
        all_page = svc.fetch_project_documents_page(
            session,
            project_id,
            tag_filter="test_tag, tag 2",
            tag_match_mode="all",
            sort_by="file_name",
            sort_dir="asc",
            limit=25,
            offset=0,
        )

    assert [dto.file_name for dto in any_page[:3]] == [
        "doc_any_all",
        "doc_only_first",
        "doc_only_second",
    ]
    assert [dto.file_name for dto in all_page] == ["doc_any_all"]


def test_document_picker_exact_document_id_filter(doc_picker_engine):
    svc = DocumentService()
    with Session(doc_picker_engine) as session:
        project_id = _seed_project_docs(session, count=5)
        target_doc = (
            session.query(SourceDocument)
            .join(SourceCorpus, SourceDocument.corpus_id == SourceCorpus.corpus_id)
            .filter(SourceCorpus.project_id == project_id)
            .order_by(SourceDocument.doc_id.asc())
            .first()
        )
        assert target_doc is not None
        page = svc.fetch_project_documents_page(
            session,
            project_id,
            document_id=int(target_doc.doc_id),
            limit=25,
            offset=0,
        )

    assert len(page) == 1
    assert page[0].doc_id == int(target_doc.doc_id)


def test_document_picker_frequent_tags_are_counted_by_normalized_tokens(doc_picker_engine):
    svc = DocumentService()
    with Session(doc_picker_engine) as session:
        project_id = _seed_project_docs(session, count=8)
        docs = (
            session.query(SourceDocument)
            .join(SourceCorpus, SourceDocument.corpus_id == SourceCorpus.corpus_id)
            .filter(SourceCorpus.project_id == project_id)
            .order_by(SourceDocument.doc_id.asc())
            .all()
        )
        for doc in docs:
            doc.tag = None
        docs[0].tag = "test_tag, tag 2"
        docs[1].tag = "test_tag"
        docs[2].tag = "tag 2"
        docs[3].tag = "alpha"
        session.commit()

        top_tags = svc.get_project_frequent_tags(session, project_id, limit=5)

    assert top_tags[:3] == ["tag 2", "test_tag", "alpha"]


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
    settings = _FakeSettings()

    monkeypatch.setattr(
        "app.ui.sentences_view.DBService.get_instance",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "app.ui.sentences_view.SettingsService.get_instance",
        lambda: settings,
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


def test_sentences_view_restores_document_filter_between_instances(monkeypatch, qtbot):
    calls = []
    settings = _FakeSettings()

    monkeypatch.setattr(
        "app.ui.sentences_view.DBService.get_instance",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "app.ui.sentences_view.SettingsService.get_instance",
        lambda: settings,
    )
    monkeypatch.setattr(
        SentencesView,
        "_reload",
        lambda self: calls.append(self._doc_filter),
    )

    first = SentencesView(project_id=11)
    qtbot.addWidget(first)
    calls.clear()
    first._doc_filter = 777
    first.doc_filter_label.setText("אקסיומה")
    first._save_view_state()

    second = SentencesView(project_id=11)
    qtbot.addWidget(second)

    assert second._doc_filter == 777
    assert second.doc_filter_label.text() == "אקסיומה"
    assert calls and calls[-1] == 777


def test_sentences_view_document_filter_state_is_project_scoped(monkeypatch, qtbot):
    settings = _FakeSettings()

    monkeypatch.setattr(
        "app.ui.sentences_view.DBService.get_instance",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "app.ui.sentences_view.SettingsService.get_instance",
        lambda: settings,
    )
    monkeypatch.setattr(
        SentencesView,
        "_reload",
        lambda self: None,
    )

    first = SentencesView(project_id=11)
    qtbot.addWidget(first)
    first._doc_filter = 777
    first.doc_filter_label.setText("Doc 777")
    first._save_view_state()

    second = SentencesView(project_id=12)
    qtbot.addWidget(second)

    assert second._doc_filter is None
    assert second.doc_filter_label.text() == "All Documents"


def test_sentences_view_clears_stale_saved_document_filter(monkeypatch, qtbot):
    settings = _FakeSettings()
    settings.set_value("sentences_view/project_11/doc_filter_id", "777")
    settings.set_value("sentences_view/project_11/doc_filter_name", "Stale Doc")

    class _FakeResult:
        def first(self):
            return None

    class _FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, _stmt):
            return _FakeResult()

    monkeypatch.setattr(
        "app.ui.sentences_view.DBService.get_instance",
        lambda: SimpleNamespace(get_read_session=lambda: _FakeSession()),
    )
    monkeypatch.setattr(
        "app.ui.sentences_view.SettingsService.get_instance",
        lambda: settings,
    )
    monkeypatch.setattr(
        SentencesView,
        "_reload",
        lambda self: None,
    )

    view = SentencesView(project_id=11)
    qtbot.addWidget(view)

    assert view._doc_filter is None
    assert view.doc_filter_label.text() == "All Documents"
    assert settings.get_string("sentences_view/project_11/doc_filter_id", "") == ""
    assert settings.get_string("sentences_view/project_11/doc_filter_name", "") == "All Documents"


def test_document_picker_quick_tag_toggle_and_clear(monkeypatch, qtbot):
    monkeypatch.setattr(DocumentPickerDialog, "_reload", lambda self, reset_page: None)
    dlg = DocumentPickerDialog(project_id=1, settings=_FakeSettings())
    qtbot.addWidget(dlg)

    dlg._render_quick_tags(["test_tag", "tag 2"])
    dlg._toggle_quick_tag("test_tag")
    assert dlg.tag_edit.text() == "test_tag"

    dlg._toggle_quick_tag("tag 2")
    assert dlg.tag_edit.text() == "test_tag, tag 2"
    assert dlg._current_tag_mode() == "any"

    dlg._toggle_quick_tag("test_tag")
    assert dlg.tag_edit.text() == "tag 2"

    dlg._clear_filters()
    assert dlg.tag_edit.text() == ""
    assert dlg.document_edit.text() == ""
    assert dlg.topic_edit.text() == ""
    assert dlg.document_id_edit.text() == ""


class _FakeSettings:
    def __init__(self):
        self.values = {}

    def get_int(self, key: str, default: int = 0) -> int:
        try:
            return int(self.values.get(key, default))
        except (TypeError, ValueError):
            return int(default)

    def get_string(self, key: str, default: str = "") -> str:
        return str(self.values.get(key, default))

    def set_value(self, key: str, value):
        self.values[key] = value


def test_document_picker_restores_filter_state_between_dialog_instances(monkeypatch, qtbot):
    settings = _FakeSettings()
    monkeypatch.setattr(DocumentPickerDialog, "_reload", lambda self, reset_page: None)

    first = DocumentPickerDialog(project_id=7, settings=settings)
    qtbot.addWidget(first)
    first.document_edit.setText("???????")
    first.document_id_edit.setText("42")
    first.topic_edit.setText("math")
    first.tag_edit.setText("test_tag, tag 2")
    first.level_combo.setCurrentText("aleph")
    first.tag_mode_combo.setCurrentText("All tags")
    first._save_filter_state()

    second = DocumentPickerDialog(project_id=7, settings=settings)
    qtbot.addWidget(second)

    assert second.document_edit.text() == "???????"
    assert second.document_id_edit.text() == "42"
    assert second.topic_edit.text() == "math"
    assert second.tag_edit.text() == "test_tag, tag 2"
    assert second.level_combo.currentText() == "aleph"
    assert second.tag_mode_combo.currentText() == "All tags"


def test_document_picker_filter_state_is_project_scoped(monkeypatch, qtbot):
    settings = _FakeSettings()
    monkeypatch.setattr(DocumentPickerDialog, "_reload", lambda self, reset_page: None)

    first = DocumentPickerDialog(project_id=7, settings=settings)
    qtbot.addWidget(first)
    first.document_edit.setText("alpha")
    first._save_filter_state()

    second = DocumentPickerDialog(project_id=8, settings=settings)
    qtbot.addWidget(second)

    assert second.document_edit.text() == ""
