"""Study service: global SRS progress (SM-2) and due queue utilities."""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional

from sqlalchemy import asc, select
from sqlalchemy.orm import Session

from app.domain.dto import StudyCardDTO, StudyProgressSummaryDTO
from app.infra.sa_models import StudyProgress, TMGlobal, UserDictionaryItem

logger = logging.getLogger(__name__)


class StudyService:
    """SRS engine and queue resolver."""

    RATING_TO_QUALITY = {
        "again": 1,
        "hard": 3,
        "good": 4,
        "easy": 5,
    }
    MASTERED_INTERVAL_DAYS = 21
    MASTERED_MIN_REVIEWS = 3
    MIN_EASE_FACTOR = 1.3

    @staticmethod
    def _now(now: Optional[datetime] = None) -> datetime:
        value = now or datetime.now(timezone.utc)
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _to_iso(dt_value: datetime) -> str:
        return dt_value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    @staticmethod
    def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
        if not ts:
            return None
        value = ts.strip()
        if not value:
            return None
        try:
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            dt_value = datetime.fromisoformat(value)
            if dt_value.tzinfo is None:
                dt_value = dt_value.replace(tzinfo=timezone.utc)
            return dt_value.astimezone(timezone.utc)
        except Exception:
            return None

    def ensure_progress(
        self,
        session: Session,
        canonical_hash: str,
        now: Optional[datetime] = None,
    ) -> int:
        """Ensure global progress row exists for canonical hash."""
        clean_hash = (canonical_hash or "").strip()
        if not clean_hash:
            raise ValueError("canonical_hash is required")

        row = session.execute(
            select(StudyProgress).where(StudyProgress.canonical_hash == clean_hash)
        ).scalar_one_or_none()
        if row:
            return row.id

        now_dt = self._now(now)
        now_str = self._to_iso(now_dt)
        row = StudyProgress(
            canonical_hash=clean_hash,
            first_seen_at=now_str,
            due_at=now_str,
            review_count=0,
            lapse_count=0,
            interval_days=0,
            ease_factor=2.5,
            updated_at=now_str,
        )
        session.add(row)
        session.flush()
        return row.id

    def seed_progress_state(
        self,
        session: Session,
        progress_id: int,
        state: str,
        now: Optional[datetime] = None,
    ) -> None:
        """Optional compatibility seed for legacy imported `study_state` values."""
        row = session.get(StudyProgress, progress_id)
        if not row:
            return

        state_key = (state or "").strip().lower()
        if state_key in ("", "new", "suspended"):
            return

        now_dt = self._now(now)
        now_str = self._to_iso(now_dt)

        if state_key == "learning":
            if (row.review_count or 0) <= 0:
                row.review_count = 1
                row.interval_days = 1
                row.last_quality = 4
                row.last_review_at = now_str
                row.due_at = self._to_iso(now_dt + timedelta(days=1))
                row.updated_at = now_str
            return

        if state_key == "mastered":
            if (row.review_count or 0) < self.MASTERED_MIN_REVIEWS:
                row.review_count = self.MASTERED_MIN_REVIEWS
                row.interval_days = 30
                row.ease_factor = max(float(row.ease_factor or 2.5), 2.5)
                row.last_quality = 5
                row.last_review_at = now_str
                row.due_at = self._to_iso(now_dt + timedelta(days=30))
                row.updated_at = now_str

    def get_progress_summaries(
        self,
        session: Session,
        canonical_hashes: List[str],
        now: Optional[datetime] = None,
    ) -> Dict[str, StudyProgressSummaryDTO]:
        """Resolve progress summaries in batch."""
        now_dt = self._now(now)
        keys = sorted({(h or "").strip() for h in canonical_hashes if (h or "").strip()})
        if not keys:
            return {}

        rows = session.execute(
            select(StudyProgress).where(StudyProgress.canonical_hash.in_(keys))
        ).scalars().all()
        by_hash = {row.canonical_hash: row for row in rows}

        result: Dict[str, StudyProgressSummaryDTO] = {}
        for key in keys:
            row = by_hash.get(key)
            if not row:
                summary = StudyProgressSummaryDTO(
                    progress_id=None,
                    canonical_hash=key,
                    first_seen_at=None,
                    last_review_at=None,
                    due_at=None,
                    review_count=0,
                    lapse_count=0,
                    interval_days=0,
                    ease_factor=2.5,
                    last_quality=None,
                    last_grade=None,
                    last_graded_at=None,
                )
            else:
                summary = StudyProgressSummaryDTO(
                    progress_id=row.id,
                    canonical_hash=row.canonical_hash,
                    first_seen_at=row.first_seen_at,
                    last_review_at=row.last_review_at,
                    due_at=row.due_at,
                    review_count=row.review_count or 0,
                    lapse_count=row.lapse_count or 0,
                    interval_days=row.interval_days or 0,
                    ease_factor=float(row.ease_factor or 2.5),
                    last_quality=row.last_quality,
                    last_grade=row.last_grade,
                    last_graded_at=row.last_graded_at,
                )

            summary.study_state = self.compute_study_state(summary, now_dt)
            summary.due_human = self.compute_due_human(summary, now_dt)
            result[key] = summary

        return result

    def get_due_queue(
        self,
        session: Session,
        dictionary_id: int | None,
        scope_origin_project_id: int | None,
        limit: int,
        now: Optional[datetime] = None,
    ) -> List[StudyCardDTO]:
        """Get due cards ordered deterministically."""
        now_dt = self._now(now)
        now_str = self._to_iso(now_dt)

        stmt = (
            select(UserDictionaryItem, StudyProgress, TMGlobal)
            .select_from(UserDictionaryItem)
            .join(StudyProgress, StudyProgress.id == UserDictionaryItem.study_progress_id)
            .outerjoin(
                TMGlobal,
                (
                    (TMGlobal.src_lang == UserDictionaryItem.src_lang)
                    & (TMGlobal.tgt_lang == UserDictionaryItem.tgt_lang)
                    & (TMGlobal.kind == UserDictionaryItem.kind)
                    & (TMGlobal.src_norm == UserDictionaryItem.src_norm)
                ),
            )
            .where(UserDictionaryItem.is_suspended == 0)
            .where(UserDictionaryItem.is_noise == 0)
            .where(StudyProgress.due_at <= now_str)
        )
        if dictionary_id is not None:
            stmt = stmt.where(UserDictionaryItem.dictionary_id == dictionary_id)
        if scope_origin_project_id is not None:
            stmt = stmt.where(UserDictionaryItem.origin_project_id == scope_origin_project_id)

        stmt = stmt.order_by(
            asc(StudyProgress.due_at),
            asc(StudyProgress.review_count),
            asc(UserDictionaryItem.item_id),
        ).limit(max(int(limit), 1))

        cards: List[StudyCardDTO] = []
        for item, progress, tm_global in session.execute(stmt).all():
            summary = StudyProgressSummaryDTO(
                progress_id=progress.id,
                canonical_hash=progress.canonical_hash,
                first_seen_at=progress.first_seen_at,
                last_review_at=progress.last_review_at,
                due_at=progress.due_at,
                review_count=progress.review_count or 0,
                lapse_count=progress.lapse_count or 0,
                interval_days=progress.interval_days or 0,
                ease_factor=float(progress.ease_factor or 2.5),
                last_quality=progress.last_quality,
                last_grade=progress.last_grade,
                last_graded_at=progress.last_graded_at,
            )
            summary.study_state = self.compute_study_state(summary, now_dt)
            summary.due_human = self.compute_due_human(summary, now_dt)
            translation_tier = self.compute_translation_tier(
                translation=(tm_global.translation if tm_global else None),
                status=(tm_global.status if tm_global else None),
                origin=(tm_global.origin if tm_global else None),
            )
            cards.append(
                StudyCardDTO(
                    item_id=item.item_id,
                    dictionary_id=item.dictionary_id,
                    canonical_hash=item.canonical_hash,
                    kind=item.kind,
                    src_lang=item.src_lang,
                    tgt_lang=item.tgt_lang,
                    src_text=item.src_text,
                    src_norm=item.src_norm,
                    translation=(tm_global.translation if tm_global else "") or "",
                    translation_tier=translation_tier,
                    origin_kind=self.compute_origin_kind(
                        origin_project_id=item.origin_project_id,
                        origin_source_ref=item.origin_source_ref,
                        origin_entity_type=item.origin_entity_type,
                    ),
                    study_state=summary.study_state,
                    due_human=summary.due_human,
                    progress_id=summary.progress_id,
                    review_count=summary.review_count,
                    lapse_count=summary.lapse_count,
                    interval_days=summary.interval_days,
                    ease_factor=summary.ease_factor,
                )
            )
        return cards

    def apply_review(
        self,
        session: Session,
        progress_id: int,
        rating: str,
        now: Optional[datetime] = None,
    ) -> StudyProgressSummaryDTO:
        """Apply SM-2 review rating and return updated summary."""
        row = session.get(StudyProgress, progress_id)
        if not row:
            raise ValueError(f"study_progress not found: {progress_id}")

        rating_key = (rating or "").strip().lower()
        if rating_key not in self.RATING_TO_QUALITY:
            raise ValueError(f"Unsupported review rating: {rating}")
        q = self.RATING_TO_QUALITY[rating_key]

        now_dt = self._now(now)
        now_str = self._to_iso(now_dt)

        review_count_before = int(row.review_count or 0)
        interval_before = int(row.interval_days or 0)
        ef_before = float(row.ease_factor or 2.5)

        ef_after = ef_before + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
        ef_after = max(self.MIN_EASE_FACTOR, ef_after)

        if q < 3:
            row.review_count = 0
            row.interval_days = 1
            row.lapse_count = int(row.lapse_count or 0) + 1
        else:
            if review_count_before == 0:
                interval_days = 1
            elif review_count_before == 1:
                interval_days = 6
            else:
                interval_days = max(1, round(max(interval_before, 1) * ef_after))
            row.review_count = review_count_before + 1
            row.interval_days = interval_days

        row.ease_factor = ef_after
        row.last_quality = q
        row.last_review_at = now_str
        row.last_grade = rating_key
        row.last_graded_at = now_str
        row.due_at = self._to_iso(now_dt + timedelta(days=int(row.interval_days or 0)))
        row.updated_at = now_str
        session.flush()

        summary = StudyProgressSummaryDTO(
            progress_id=row.id,
            canonical_hash=row.canonical_hash,
            first_seen_at=row.first_seen_at,
            last_review_at=row.last_review_at,
            due_at=row.due_at,
            review_count=row.review_count or 0,
            lapse_count=row.lapse_count or 0,
            interval_days=row.interval_days or 0,
            ease_factor=float(row.ease_factor or 2.5),
            last_quality=row.last_quality,
            last_grade=row.last_grade,
            last_graded_at=row.last_graded_at,
        )
        summary.study_state = self.compute_study_state(summary, now_dt)
        summary.due_human = self.compute_due_human(summary, now_dt)
        return summary

    def compute_study_state(
        self,
        summary: StudyProgressSummaryDTO,
        now: Optional[datetime] = None,
    ) -> str:
        """Compute semantic study state from summary."""
        if summary.is_suspended:
            return "suspended"
        if int(summary.review_count or 0) <= 0:
            return "new"

        now_dt = self._now(now)
        due_dt = self._parse_iso(summary.due_at)
        if due_dt and due_dt <= now_dt:
            return "due"

        if (
            int(summary.review_count or 0) >= self.MASTERED_MIN_REVIEWS
            and int(summary.interval_days or 0) >= self.MASTERED_INTERVAL_DAYS
        ):
            return "mastered"

        return "learning"

    def compute_due_human(
        self,
        summary: StudyProgressSummaryDTO,
        now: Optional[datetime] = None,
    ) -> Optional[str]:
        """Human-readable due status."""
        due_dt = self._parse_iso(summary.due_at)
        if due_dt is None:
            return None

        now_dt = self._now(now)
        due_date = due_dt.date()
        now_date = now_dt.date()
        delta_days = (due_date - now_date).days
        if delta_days == 0:
            return "Due today"
        if delta_days > 0:
            return f"in {delta_days}d"
        return f"Overdue {abs(delta_days)}d"

    @staticmethod
    def compute_translation_tier(
        *,
        translation: Optional[str],
        status: Optional[str],
        origin: Optional[str],
    ) -> str:
        """Compute translation tier token from tm_global fields."""
        if not (translation or "").strip():
            return "missing"
        if (status or "").lower() == "deprecated":
            return "deprecated"
        if (status or "").lower() == "approved":
            return "approved"
        if (origin or "").lower() in {"user_edit", "import", "mt_accept", "merge", "revert"}:
            return "user"
        return "mt"

    @staticmethod
    def compute_origin_kind(
        *,
        origin_project_id: Optional[int],
        origin_source_ref: Optional[str],
        origin_entity_type: Optional[str],
    ) -> str:
        """Compute origin token for UI."""
        if origin_project_id is not None:
            return "project"
        source_ref = (origin_source_ref or "").lower()
        if "import" in source_ref:
            return "imported"
        if (origin_entity_type or "").lower() == "manual":
            return "manual"
        return "manual"
