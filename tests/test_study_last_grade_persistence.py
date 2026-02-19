"""Tests for persisting last review grade in study_progress."""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.infra.sa_models import StudyProgress, UserDictionary, UserDictionaryItem
from app.services.study_service import StudyService
from app.services.user_dictionary_service import UserDictionaryService


def _iso(dt_value: datetime) -> str:
    return dt_value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _engine():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_engine(f"sqlite:///{tmp.name}")
    StudyProgress.__table__.create(engine, checkfirst=True)
    UserDictionary.__table__.create(engine, checkfirst=True)
    UserDictionaryItem.__table__.create(engine, checkfirst=True)
    return engine, Path(tmp.name)


def test_review_persists_last_grade_and_last_graded_at():
    engine, path = _engine()
    try:
        study_service = StudyService()
        now = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
        with Session(engine) as session:
            progress_id = study_service.ensure_progress(session, "hash-grade")
            summary = study_service.apply_review(session, progress_id, "good", now=now)
            session.commit()

            row = session.execute(select(StudyProgress).where(StudyProgress.id == progress_id)).scalar_one()
            assert row.last_grade == "good"
            assert row.last_graded_at == _iso(now)
            assert summary.last_grade == "good"
            assert summary.last_graded_at == _iso(now)
    finally:
        engine.dispose()
        path.unlink(missing_ok=True)


def test_due_now_does_not_modify_last_grade_history():
    engine, path = _engine()
    try:
        study_service = StudyService()
        user_dict_service = UserDictionaryService()
        now = datetime(2026, 2, 19, 13, 0, 0, tzinfo=timezone.utc)

        with Session(engine) as session:
            dictionary = UserDictionary(name="Deck Last Grade")
            session.add(dictionary)
            session.flush()

            canonical_hash = user_dict_service.build_canonical_hash("he", "ru", "lemma", "alpha")
            progress_id = study_service.ensure_progress(session, canonical_hash)
            study_service.apply_review(session, progress_id, "hard", now=now)
            item = UserDictionaryItem(
                dictionary_id=dictionary.dictionary_id,
                kind="lemma",
                src_lang="he",
                tgt_lang="ru",
                src_text="alpha",
                src_norm="alpha",
                canonical_hash=canonical_hash,
                tags_json="[]",
                is_noise=0,
                study_state="learning",
                study_progress_id=progress_id,
            )
            session.add(item)
            session.flush()

            before = session.get(StudyProgress, progress_id)
            before_grade = before.last_grade
            before_graded_at = before.last_graded_at
            before_review_count = before.review_count
            before_lapse_count = before.lapse_count
            before_interval = before.interval_days
            before_ef = before.ease_factor

            changed = user_dict_service.set_items_due_now_bulk(session, [item.item_id])
            session.commit()
            assert changed == 1

            after = session.get(StudyProgress, progress_id)
            assert after.last_grade == before_grade
            assert after.last_graded_at == before_graded_at
            assert after.review_count == before_review_count
            assert after.lapse_count == before_lapse_count
            assert after.interval_days == before_interval
            assert after.ease_factor == before_ef
    finally:
        engine.dispose()
        path.unlink(missing_ok=True)
