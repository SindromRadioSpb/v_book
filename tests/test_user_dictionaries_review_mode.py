"""Review mode wiring tests for User Dictionaries."""

from __future__ import annotations

import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.domain.dto import StudyCardDTO
from app.infra.sa_models import StudyProgress
from app.ui.user_dictionaries_view import UserDictionariesView


def _iso(dt_value: datetime) -> str:
    return dt_value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class _FakeDBService:
    def __init__(self, engine):
        self._engine = engine

    @contextmanager
    def get_session(self):
        with Session(self._engine) as session:
            yield session


def _setup_engine():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_engine(f"sqlite:///{tmp.name}")
    StudyProgress.__table__.create(engine, checkfirst=True)
    return engine, Path(tmp.name)


def _make_card(progress_id: int) -> StudyCardDTO:
    return StudyCardDTO(
        item_id=1,
        dictionary_id=1,
        canonical_hash="hash-card",
        kind="lemma",
        src_lang="he",
        tgt_lang="ru",
        src_text="alpha",
        src_norm="alpha",
        translation="ru-alpha",
        translation_tier="missing",
        origin_kind="manual",
        study_state="due",
        due_human="Due today",
        progress_id=progress_id,
        review_count=1,
        lapse_count=0,
        interval_days=1,
        ease_factor=2.5,
    )


def test_review_good_updates_due_and_state(monkeypatch, qtbot):
    engine, path = _setup_engine()
    try:
        now = datetime.now(timezone.utc)
        with Session(engine) as session:
            row = StudyProgress(
                canonical_hash="hash-card",
                first_seen_at=_iso(now - timedelta(days=2)),
                due_at=_iso(now - timedelta(days=1)),
                review_count=0,
                lapse_count=0,
                interval_days=0,
                ease_factor=2.5,
                updated_at=_iso(now),
            )
            session.add(row)
            session.commit()
            progress_id = row.id

        monkeypatch.setattr(UserDictionariesView, "load_dictionaries", lambda self: None)
        monkeypatch.setattr(UserDictionariesView, "load_items", lambda self: None)
        monkeypatch.setattr(
            "app.ui.user_dictionaries_view.DBService.get_instance", lambda: _FakeDBService(engine)
        )

        view = UserDictionariesView(project_id=None)
        qtbot.addWidget(view)
        view._review_cards = [_make_card(progress_id)]
        view._review_index = 0
        view._render_review_card()
        view.review_translation_edit.setText("ru-alpha")
        view.load_review_queue = lambda reset_index=False: None

        view.on_review_rate("good")

        with Session(engine) as session:
            updated = session.execute(
                select(StudyProgress).where(StudyProgress.id == progress_id)
            ).scalar_one()
            assert updated.review_count == 1
            assert updated.interval_days == 1
    finally:
        engine.dispose()
        path.unlink(missing_ok=True)


def test_review_again_increments_lapse_and_resets(monkeypatch, qtbot):
    engine, path = _setup_engine()
    try:
        now = datetime.now(timezone.utc)
        with Session(engine) as session:
            row = StudyProgress(
                canonical_hash="hash-card",
                first_seen_at=_iso(now - timedelta(days=10)),
                due_at=_iso(now - timedelta(days=1)),
                review_count=2,
                lapse_count=0,
                interval_days=6,
                ease_factor=2.5,
                updated_at=_iso(now),
            )
            session.add(row)
            session.commit()
            progress_id = row.id

        monkeypatch.setattr(UserDictionariesView, "load_dictionaries", lambda self: None)
        monkeypatch.setattr(UserDictionariesView, "load_items", lambda self: None)
        monkeypatch.setattr(
            "app.ui.user_dictionaries_view.DBService.get_instance", lambda: _FakeDBService(engine)
        )

        view = UserDictionariesView(project_id=None)
        qtbot.addWidget(view)
        view._review_cards = [_make_card(progress_id)]
        view._review_index = 0
        view._render_review_card()
        view.review_translation_edit.setText("ru-alpha")
        view.load_review_queue = lambda reset_index=False: None

        view.on_review_rate("again")

        with Session(engine) as session:
            updated = session.execute(
                select(StudyProgress).where(StudyProgress.id == progress_id)
            ).scalar_one()
            assert updated.review_count == 0
            assert updated.interval_days == 1
            assert updated.lapse_count == 1
    finally:
        engine.dispose()
        path.unlink(missing_ok=True)


def test_review_play_audio_uses_current_card(monkeypatch, qtbot):
    engine, path = _setup_engine()
    try:
        monkeypatch.setattr(UserDictionariesView, "load_dictionaries", lambda self: None)
        monkeypatch.setattr(UserDictionariesView, "load_items", lambda self: None)
        monkeypatch.setattr(
            "app.ui.user_dictionaries_view.DBService.get_instance", lambda: _FakeDBService(engine)
        )

        view = UserDictionariesView(project_id=None)
        qtbot.addWidget(view)
        view._review_cards = [_make_card(progress_id=1)]
        view._review_index = 0
        view._render_review_card()

        captured = {}

        def _capture_play(items, *, play_mode, start_immediately=False):
            captured["items"] = items
            captured["play_mode"] = play_mode
            captured["start_immediately"] = start_immediately

        monkeypatch.setattr(view, "_play_audio_items", _capture_play)
        view.review_play_audio_btn.click()

        assert captured["play_mode"] == "enqueue"
        assert captured["start_immediately"] is True
        assert captured["items"] == [
            {
                "src_lang": "he",
                "src_norm": "alpha",
                "src_text": "alpha",
            }
        ]
    finally:
        engine.dispose()
        path.unlink(missing_ok=True)
