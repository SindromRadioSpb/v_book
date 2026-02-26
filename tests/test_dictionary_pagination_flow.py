"""Dictionary pagination/sort and anti-stale request behavior tests."""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.infra.sa_models import DictProject, Lemma, LemmaProjectStat, Library
from app.services.dictionary_service import DictionaryService
from app.ui.dictionary_view import DictionaryView


@pytest.fixture
def dictionary_engine():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        Library.__table__.create(engine, checkfirst=True)
        DictProject.__table__.create(engine, checkfirst=True)
        Lemma.__table__.create(engine, checkfirst=True)
        LemmaProjectStat.__table__.create(engine, checkfirst=True)
        yield engine
    finally:
        engine.dispose()
        Path(db_path).unlink(missing_ok=True)


def _seed_lemmas(session: Session, count: int = 120) -> int:
    library = Library(name="L")
    session.add(library)
    session.flush()
    project = DictProject(library_id=library.library_id, name="P", src_lang="he", tgt_lang="ru")
    session.add(project)
    session.flush()

    for i in range(count):
        lemma = Lemma(
            project_id=project.project_id,
            lemma_text=f"lemma_{count - i:04d}",
            pos="NOUN",
            is_noise=0,
        )
        session.add(lemma)
        session.flush()
        session.add(
            LemmaProjectStat(
                project_id=project.project_id,
                lemma_id=lemma.lemma_id,
                freq_abs=count - i,
                doc_freq=(i % 23) + 1,
            )
        )

    session.commit()
    return int(project.project_id)


def test_dictionary_global_sort_before_pagination(dictionary_engine):
    svc = DictionaryService()
    filters = {"pos": "All", "hide_noise": True, "search": ""}

    with Session(dictionary_engine) as session:
        project_id = _seed_lemmas(session, count=120)
        all_rows = svc.search_lemmas(
            session,
            project_id,
            filters=filters,
            limit=200,
            offset=0,
            sort_column="lemma_text",
            sort_direction="asc",
        )
        expected_page_2 = [lemma.lemma_text for lemma, _stat in all_rows[20:40]]

        page_2 = svc.search_lemmas(
            session,
            project_id,
            filters=filters,
            limit=20,
            offset=20,
            sort_column="lemma_text",
            sort_direction="asc",
        )
        got_page_2 = [lemma.lemma_text for lemma, _stat in page_2]

    assert got_page_2 == expected_page_2


def test_dictionary_request_id_ignores_stale(monkeypatch, qtbot):
    monkeypatch.setattr(DictionaryView, "perform_search", lambda self: None)
    monkeypatch.setattr("app.ui.dictionary_view.QTimer.singleShot", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "app.ui.dictionary_view.DBService.get_instance",
        lambda: SimpleNamespace(),
    )

    view = DictionaryView(project_id=1)
    qtbot.addWidget(view)

    rendered = []
    monkeypatch.setattr(view.lemma_model, "update_lemmas", lambda lemmas: rendered.append(list(lemmas)))
    monkeypatch.setattr(view, "start_translation_worker", lambda lemmas: None)

    row = (
        SimpleNamespace(
            lemma_id=1,
            lemma_text="alpha",
            pos="NOUN",
            entity_class=None,
            is_noise=0,
            noise_reason=None,
            norm_text="alpha",
        ),
        SimpleNamespace(freq_abs=10, doc_freq=4),
    )

    view._active_search_seq = 2
    view.on_search_results([row], request_seq=1)
    assert rendered == []

    view.on_search_results([row], request_seq=2)
    assert len(rendered) == 1
    assert rendered[0][0].lemma_text == "alpha"

    view.total_count = 10
    view.on_search_count_ready(99, request_seq=1)
    assert view.total_count == 10

    view.on_search_count_ready(99, request_seq=2)
    assert view.total_count == 99


def test_dictionary_pagination_labels_are_ascii_safe(monkeypatch, qtbot):
    monkeypatch.setattr(DictionaryView, "perform_search", lambda self: None)
    monkeypatch.setattr("app.ui.dictionary_view.QTimer.singleShot", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "app.ui.dictionary_view.DBService.get_instance",
        lambda: SimpleNamespace(),
    )

    view = DictionaryView(project_id=1)
    qtbot.addWidget(view)

    assert view.first_btn.text() == "<<"
    assert view.prev_btn.text() == "<"
    assert view.next_btn.text() == ">"
    assert view.last_btn.text() == ">>"
    assert view.range_label.text() == "Showing 0-0 of 0"

    view.total_count = 120
    view.page_size = 25
    view.current_page = 2
    view.update_pagination_controls()
    assert view.range_label.text() == "Showing 26-50 of 120"
