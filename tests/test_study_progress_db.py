"""Database-level tests for study_progress and due queue behavior."""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.infra.sa_models import (
    DictProject,
    Library,
    SourceDocument,
    StudyProgress,
    TMEntry,
    TMGlobal,
    UserDictionary,
    UserDictionaryItem,
)
from app.services.study_service import StudyService
from app.services.user_dictionary_service import UserDictionaryService


def _iso(dt_value: datetime) -> str:
    return dt_value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _engine():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_engine(f"sqlite:///{tmp.name}")
    Library.__table__.create(engine, checkfirst=True)
    DictProject.__table__.create(engine, checkfirst=True)
    SourceDocument.__table__.create(engine, checkfirst=True)
    TMEntry.__table__.create(engine, checkfirst=True)
    TMGlobal.__table__.create(engine, checkfirst=True)
    UserDictionary.__table__.create(engine, checkfirst=True)
    StudyProgress.__table__.create(engine, checkfirst=True)
    UserDictionaryItem.__table__.create(engine, checkfirst=True)
    return engine, Path(tmp.name)


def test_ensure_progress_idempotent_unique_hash():
    engine, path = _engine()
    try:
        service = StudyService()
        with Session(engine) as session:
            p1 = service.ensure_progress(session, "hash-unique")
            p2 = service.ensure_progress(session, "hash-unique")
            session.commit()

            assert p1 == p2
            rows = session.execute(
                select(StudyProgress).where(StudyProgress.canonical_hash == "hash-unique")
            ).all()
            assert len(rows) == 1
    finally:
        engine.dispose()
        path.unlink(missing_ok=True)


def test_due_queue_excludes_suspended_items():
    engine, path = _engine()
    try:
        study_service = StudyService()
        user_dict_service = UserDictionaryService()
        now = datetime.now(timezone.utc)
        due_ts = _iso(now - timedelta(days=1))
        with Session(engine) as session:
            dictionary = UserDictionary(name="Deck A")
            session.add(dictionary)
            session.flush()

            p_keep = study_service.ensure_progress(session, "hash-keep")
            p_skip = study_service.ensure_progress(session, "hash-skip")
            keep_row = session.get(StudyProgress, p_keep)
            skip_row = session.get(StudyProgress, p_skip)
            keep_row.review_count = 1
            keep_row.interval_days = 1
            keep_row.due_at = due_ts
            skip_row.review_count = 1
            skip_row.interval_days = 1
            skip_row.due_at = due_ts
            session.flush()

            session.add_all(
                [
                    UserDictionaryItem(
                        dictionary_id=dictionary.dictionary_id,
                        kind="lemma",
                        src_lang="he",
                        tgt_lang="ru",
                        src_text="alpha",
                        src_norm="alpha",
                        canonical_hash=user_dict_service.build_canonical_hash(
                            "he", "ru", "lemma", "alpha"
                        ),
                        study_progress_id=p_keep,
                        is_noise=0,
                        is_suspended=0,
                        study_state="new",
                        tags_json="[]",
                    ),
                    UserDictionaryItem(
                        dictionary_id=dictionary.dictionary_id,
                        kind="lemma",
                        src_lang="he",
                        tgt_lang="ru",
                        src_text="beta",
                        src_norm="beta",
                        canonical_hash=user_dict_service.build_canonical_hash(
                            "he", "ru", "lemma", "beta"
                        ),
                        study_progress_id=p_skip,
                        is_noise=0,
                        is_suspended=1,
                        study_state="suspended",
                        tags_json="[]",
                    ),
                ]
            )
            session.commit()

            queue = study_service.get_due_queue(
                session=session,
                dictionary_id=dictionary.dictionary_id,
                scope_origin_project_id=None,
                limit=10,
            )
            assert len(queue) == 1
            assert queue[0].src_text == "alpha"
    finally:
        engine.dispose()
        path.unlink(missing_ok=True)


def test_due_queue_returns_due_first():
    engine, path = _engine()
    try:
        study_service = StudyService()
        user_dict_service = UserDictionaryService()
        now = datetime.now(timezone.utc)
        with Session(engine) as session:
            dictionary = UserDictionary(name="Deck B")
            session.add(dictionary)
            session.flush()

            p_old = study_service.ensure_progress(session, "hash-old")
            p_new = study_service.ensure_progress(session, "hash-new")
            old_row = session.get(StudyProgress, p_old)
            new_row = session.get(StudyProgress, p_new)
            old_row.review_count = 2
            old_row.interval_days = 6
            old_row.due_at = _iso(now - timedelta(days=3))
            new_row.review_count = 2
            new_row.interval_days = 6
            new_row.due_at = _iso(now - timedelta(days=1))
            session.flush()

            session.add_all(
                [
                    UserDictionaryItem(
                        dictionary_id=dictionary.dictionary_id,
                        kind="lemma",
                        src_lang="he",
                        tgt_lang="ru",
                        src_text="older",
                        src_norm="older",
                        canonical_hash=user_dict_service.build_canonical_hash(
                            "he", "ru", "lemma", "older"
                        ),
                        study_progress_id=p_old,
                        is_noise=0,
                        is_suspended=0,
                        study_state="learning",
                        tags_json="[]",
                    ),
                    UserDictionaryItem(
                        dictionary_id=dictionary.dictionary_id,
                        kind="lemma",
                        src_lang="he",
                        tgt_lang="ru",
                        src_text="newer",
                        src_norm="newer",
                        canonical_hash=user_dict_service.build_canonical_hash(
                            "he", "ru", "lemma", "newer"
                        ),
                        study_progress_id=p_new,
                        is_noise=0,
                        is_suspended=0,
                        study_state="learning",
                        tags_json="[]",
                    ),
                ]
            )
            session.commit()

            queue = study_service.get_due_queue(
                session=session,
                dictionary_id=dictionary.dictionary_id,
                scope_origin_project_id=None,
                limit=10,
            )
            assert len(queue) == 2
            assert queue[0].src_text == "older"
            assert queue[1].src_text == "newer"
    finally:
        engine.dispose()
        path.unlink(missing_ok=True)
