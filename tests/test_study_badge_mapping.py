"""Study badge/state mapping coverage."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domain.dto import StudyProgressSummaryDTO
from app.services.study_service import StudyService


def _iso(dt_value: datetime) -> str:
    return dt_value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def test_badge_new_when_review_count_zero():
    service = StudyService()
    now = datetime.now(timezone.utc)
    summary = StudyProgressSummaryDTO(
        progress_id=1,
        canonical_hash="hash-new",
        first_seen_at=_iso(now),
        last_review_at=None,
        due_at=_iso(now),
        review_count=0,
        lapse_count=0,
        interval_days=0,
        ease_factor=2.5,
        last_quality=None,
    )
    assert service.compute_study_state(summary, now) == "new"


def test_badge_due_when_due_at_past():
    service = StudyService()
    now = datetime.now(timezone.utc)
    summary = StudyProgressSummaryDTO(
        progress_id=1,
        canonical_hash="hash-due",
        first_seen_at=_iso(now - timedelta(days=5)),
        last_review_at=_iso(now - timedelta(days=2)),
        due_at=_iso(now - timedelta(days=1)),
        review_count=2,
        lapse_count=0,
        interval_days=6,
        ease_factor=2.5,
        last_quality=4,
    )
    assert service.compute_study_state(summary, now) == "due"


def test_badge_learning_when_due_future():
    service = StudyService()
    now = datetime.now(timezone.utc)
    summary = StudyProgressSummaryDTO(
        progress_id=1,
        canonical_hash="hash-learning",
        first_seen_at=_iso(now - timedelta(days=4)),
        last_review_at=_iso(now - timedelta(days=1)),
        due_at=_iso(now + timedelta(days=2)),
        review_count=2,
        lapse_count=0,
        interval_days=6,
        ease_factor=2.5,
        last_quality=4,
    )
    assert service.compute_study_state(summary, now) == "learning"


def test_badge_mastered_when_interval_threshold_met():
    service = StudyService()
    now = datetime.now(timezone.utc)
    summary = StudyProgressSummaryDTO(
        progress_id=1,
        canonical_hash="hash-mastered",
        first_seen_at=_iso(now - timedelta(days=40)),
        last_review_at=_iso(now - timedelta(days=3)),
        due_at=_iso(now + timedelta(days=10)),
        review_count=4,
        lapse_count=0,
        interval_days=30,
        ease_factor=2.7,
        last_quality=5,
    )
    assert service.compute_study_state(summary, now) == "mastered"


def test_badge_learning_after_again_with_zero_review_count():
    service = StudyService()
    now = datetime.now(timezone.utc)
    summary = StudyProgressSummaryDTO(
        progress_id=1,
        canonical_hash="hash-again-learning",
        first_seen_at=_iso(now - timedelta(days=3)),
        last_review_at=_iso(now - timedelta(hours=1)),
        due_at=_iso(now + timedelta(days=1)),
        review_count=0,
        lapse_count=1,
        interval_days=1,
        ease_factor=2.3,
        last_quality=1,
        last_grade="again",
        last_graded_at=_iso(now - timedelta(hours=1)),
    )
    assert service.compute_study_state(summary, now) == "learning"
