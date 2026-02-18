"""SM-2 engine coverage for StudyService."""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.infra.sa_models import StudyProgress
from app.services.study_service import StudyService


def _parse_iso(ts: str) -> datetime:
    value = ts
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt_value = datetime.fromisoformat(value)
    if dt_value.tzinfo is None:
        dt_value = dt_value.replace(tzinfo=timezone.utc)
    return dt_value.astimezone(timezone.utc)


def _engine():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_engine(f"sqlite:///{tmp.name}")
    StudyProgress.__table__.create(engine, checkfirst=True)
    return engine, Path(tmp.name)


def test_again_resets_progress_and_sets_due_tomorrow():
    engine, path = _engine()
    try:
        service = StudyService()
        with Session(engine) as session:
            progress_id = service.ensure_progress(session, "hash-again")
            service.apply_review(session, progress_id, "good")
            summary = service.apply_review(session, progress_id, "again")
            session.commit()

            row = session.execute(select(StudyProgress).where(StudyProgress.id == progress_id)).scalar_one()
            assert row.review_count == 0
            assert row.interval_days == 1
            assert row.lapse_count == 1
            due_dt = _parse_iso(row.due_at)
            now_dt = datetime.now(timezone.utc)
            assert 0 <= (due_dt.date() - now_dt.date()).days <= 1
            assert summary.study_state == "new"
    finally:
        engine.dispose()
        path.unlink(missing_ok=True)


def test_good_progression_intervals_1_then_6():
    engine, path = _engine()
    try:
        service = StudyService()
        with Session(engine) as session:
            progress_id = service.ensure_progress(session, "hash-good")
            s1 = service.apply_review(session, progress_id, "good")
            s2 = service.apply_review(session, progress_id, "good")
            session.commit()

            assert s1.interval_days == 1
            assert s2.interval_days == 6
            assert s2.review_count == 2
    finally:
        engine.dispose()
        path.unlink(missing_ok=True)


def test_easy_increases_ef_and_interval_grows():
    engine, path = _engine()
    try:
        service = StudyService()
        with Session(engine) as session:
            progress_id = service.ensure_progress(session, "hash-easy")
            service.apply_review(session, progress_id, "good")
            service.apply_review(session, progress_id, "good")
            summary = service.apply_review(session, progress_id, "easy")
            session.commit()

            assert summary.review_count == 3
            assert summary.interval_days > 6
            assert summary.ease_factor > 2.5
    finally:
        engine.dispose()
        path.unlink(missing_ok=True)


def test_ef_clamped_min_1_3():
    engine, path = _engine()
    try:
        service = StudyService()
        with Session(engine) as session:
            progress_id = service.ensure_progress(session, "hash-clamp")
            summary = None
            for _ in range(10):
                summary = service.apply_review(session, progress_id, "again")
            session.commit()

            assert summary is not None
            assert summary.ease_factor >= 1.3
            assert abs(summary.ease_factor - 1.3) < 1e-9
    finally:
        engine.dispose()
        path.unlink(missing_ok=True)

