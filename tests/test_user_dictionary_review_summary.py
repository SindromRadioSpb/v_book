"""Tests for Added/Again/Hard/Good/Easy summary counters in user dictionaries."""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.infra.sa_models import Base, StudyProgress, TMGlobal, UserDictionary, UserDictionaryItem
from app.services.user_dictionary_service import UserDictionaryService


def _iso(dt_value: datetime) -> str:
    return dt_value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _engine():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_engine(f"sqlite:///{tmp.name}")
    # Create all tables so JOIN-dependent queries (dict_project, security_audit_log) work
    Base.metadata.create_all(engine)
    return engine, Path(tmp.name)


def _add_item(
    session: Session,
    service: UserDictionaryService,
    *,
    dictionary_id: int,
    canonical_hash: str,
    grade: str | None,
    review_count: int,
    is_noise: int,
    origin_project_id: int | None,
):
    now = datetime.now(timezone.utc)
    progress = StudyProgress(
        canonical_hash=canonical_hash,
        first_seen_at=_iso(now - timedelta(days=5)),
        due_at=_iso(now - timedelta(days=1)),
        review_count=review_count,
        lapse_count=0,
        interval_days=1,
        ease_factor=2.5,
        last_grade=grade,
        last_graded_at=_iso(now - timedelta(hours=2)) if grade else None,
        updated_at=_iso(now),
    )
    session.add(progress)
    session.flush()
    session.add(
        UserDictionaryItem(
            dictionary_id=dictionary_id,
            kind="lemma",
            src_lang="he",
            tgt_lang="ru",
            src_text=f"src-{canonical_hash}",
            src_norm=f"src-{canonical_hash}",
            canonical_hash=service.build_canonical_hash(
                "he", "ru", "lemma", f"src-{canonical_hash}"
            ),
            tags_json="[]",
            is_noise=is_noise,
            study_state="new",
            study_progress_id=progress.id,
            origin_project_id=origin_project_id,
        )
    )


def test_review_summary_counts_scope_hide_noise_and_search_independence():
    engine, path = _engine()
    try:
        service = UserDictionaryService()
        with Session(engine) as session:
            dictionary_id = service.create_dictionary(session, "Deck Summary").dictionary_id
            _add_item(
                session,
                service,
                dictionary_id=dictionary_id,
                canonical_hash="h-added",
                grade=None,
                review_count=0,
                is_noise=0,
                origin_project_id=10,
            )
            _add_item(
                session,
                service,
                dictionary_id=dictionary_id,
                canonical_hash="h-again",
                grade="again",
                review_count=0,
                is_noise=0,
                origin_project_id=10,
            )
            _add_item(
                session,
                service,
                dictionary_id=dictionary_id,
                canonical_hash="h-hard",
                grade="hard",
                review_count=3,
                is_noise=0,
                origin_project_id=20,
            )
            _add_item(
                session,
                service,
                dictionary_id=dictionary_id,
                canonical_hash="h-good",
                grade="good",
                review_count=4,
                is_noise=1,
                origin_project_id=10,
            )
            _add_item(
                session,
                service,
                dictionary_id=dictionary_id,
                canonical_hash="h-easy",
                grade="easy",
                review_count=5,
                is_noise=0,
                origin_project_id=10,
            )
            session.commit()

            hidden_noise = service.get_dictionary_review_summary(
                session=session,
                dictionary_id=dictionary_id,
                scope_origin_project_id=None,
                hide_noise=True,
            )
            assert hidden_noise == {
                "words": 4,
                "added": 1,
                "again": 1,
                "hard": 1,
                "good": 0,
                "easy": 1,
            }

            all_rows = service.get_dictionary_review_summary(
                session=session,
                dictionary_id=dictionary_id,
                scope_origin_project_id=None,
                hide_noise=False,
            )
            assert all_rows == {
                "words": 5,
                "added": 1,
                "again": 1,
                "hard": 1,
                "good": 1,
                "easy": 1,
            }

            project_10 = service.get_dictionary_review_summary(
                session=session,
                dictionary_id=dictionary_id,
                scope_origin_project_id=10,
                hide_noise=False,
            )
            assert project_10 == {
                "words": 4,
                "added": 1,
                "again": 1,
                "hard": 0,
                "good": 1,
                "easy": 1,
            }

            # Summary metric is stable and does not depend on search-text filtering.
            _items, _total = service.query_items(
                session=session,
                dictionary_id=dictionary_id,
                filters={"search_text": "does-not-match-anything", "hide_noise": False},
                limit=25,
                offset=0,
                sort_column="src_text",
                sort_direction="asc",
            )
            stable_again = service.get_dictionary_review_summary(
                session=session,
                dictionary_id=dictionary_id,
                scope_origin_project_id=None,
                hide_noise=False,
            )
            assert stable_again == all_rows
    finally:
        engine.dispose()
        path.unlink(missing_ok=True)
