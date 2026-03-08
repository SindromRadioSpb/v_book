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


def test_dictionary_pos_multiselect_filter(dictionary_engine):
    svc = DictionaryService()
    with Session(dictionary_engine) as session:
        library = Library(name="L2")
        session.add(library)
        session.flush()
        project = DictProject(library_id=library.library_id, name="P2", src_lang="he", tgt_lang="ru")
        session.add(project)
        session.flush()

        seed_rows = [
            ("alpha", "NOUN", 30, 5),
            ("beta", "VERB", 20, 4),
            ("gamma", "ADJ", 10, 3),
        ]
        for lemma_text, pos, freq_abs, doc_freq in seed_rows:
            lemma = Lemma(
                project_id=project.project_id,
                lemma_text=lemma_text,
                pos=pos,
                is_noise=0,
            )
            session.add(lemma)
            session.flush()
            session.add(
                LemmaProjectStat(
                    project_id=project.project_id,
                    lemma_id=lemma.lemma_id,
                    freq_abs=freq_abs,
                    doc_freq=doc_freq,
                )
            )
        session.commit()

        filters = {"pos_tags": ["NOUN", "VERB"], "hide_noise": True, "search": ""}
        rows = svc.search_lemmas(
            session,
            int(project.project_id),
            filters=filters,
            limit=100,
            offset=0,
            sort_column="lemma_text",
            sort_direction="asc",
        )
        count = svc.count_lemmas(session, int(project.project_id), filters=filters)

    assert len(rows) == 2
    assert count == 2
    assert {lemma.pos for lemma, _stat in rows} == {"NOUN", "VERB"}


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


def test_dictionary_build_filters_supports_pos_multiselect(monkeypatch, qtbot):
    monkeypatch.setattr(DictionaryView, "perform_search", lambda self: None)
    monkeypatch.setattr("app.ui.dictionary_view.QTimer.singleShot", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "app.ui.dictionary_view.DBService.get_instance",
        lambda: SimpleNamespace(),
    )

    view = DictionaryView(project_id=1)
    qtbot.addWidget(view)

    view.selected_pos = ["NOUN", "VERB"]
    view.search_edit.setText("abc")
    view.hide_noise_checkbox.setChecked(False)
    filters = view.build_filters()

    assert filters["pos_tags"] == ["NOUN", "VERB"]
    assert filters["pos"] == "All"
    assert filters["search"] == "abc"
    assert filters["hide_noise"] is False


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


def test_dictionary_refresh_current_page_skips_recount(monkeypatch):
    view = DictionaryView.__new__(DictionaryView)
    captured = {}
    view.perform_search = lambda **kwargs: captured.update(kwargs)

    DictionaryView.refresh_current_page_after_operation(view)

    assert captured == {
        "include_total_count": False,
        "preserve_existing_state": True,
    }


def test_dictionary_rehydrates_visible_state_from_previous_page():
    view = DictionaryView.__new__(DictionaryView)

    previous_translation_result = SimpleNamespace(source="tm", status="approved")
    view.lemma_model = SimpleNamespace(
        lemmas=[
            SimpleNamespace(
                lemma_id=11,
                translation="перевод",
                status="approved",
                in_user_dictionary_count=1,
                study_tooltip="tooltip",
                study_state="learning",
                study_due_human="soon",
                last_grade="good",
                last_graded_at="2026-03-08",
                translation_tier="approved",
                audio_status="ready",
                pronunciation_text="נִקּוּד",
                pronunciation_source="manual",
                pronunciation_confidence=0.9,
                pronunciation_qc="ok",
            )
        ],
        translation_results={0: previous_translation_result},
    )

    snapshot = DictionaryView._snapshot_lemma_state(view)
    lemmas = [
        SimpleNamespace(
            lemma_id=11,
            translation=None,
            status="auto",
            in_user_dictionary_count=0,
            study_tooltip=None,
            study_state=None,
            study_due_human=None,
            last_grade=None,
            last_graded_at=None,
            translation_tier=None,
            audio_status=None,
            pronunciation_text=None,
            pronunciation_source=None,
            pronunciation_confidence=None,
            pronunciation_qc=None,
        )
    ]

    translation_results = DictionaryView._rehydrate_lemma_state(view, lemmas, snapshot)

    assert lemmas[0].translation == "перевод"
    assert lemmas[0].audio_status == "ready"
    assert lemmas[0].pronunciation_text == "נִקּוּד"
    assert translation_results[0] is previous_translation_result
