"""Audio usage tracker for budget-guard enforcement."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AudioBudgetLimits:
    """Minimal limit contract used by audio usage tracker."""

    max_chars_per_request: int = 10000
    max_requests_per_minute: int = 60
    max_chars_per_day: int | None = None
    max_chars_per_month: int | None = None
    max_requests_per_day: int | None = None
    fail_closed: bool = True

    def has_budget_guards(self) -> bool:
        return (
            self.max_chars_per_day is not None
            or self.max_chars_per_month is not None
            or self.max_requests_per_day is not None
            or self.max_requests_per_minute is not None
        )


class AudioUsageTracker:
    """Tracks audio provider usage by minute/day/month buckets."""

    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(UTC)

    def can_spend(
        self,
        provider_id: str,
        char_count: int,
        limits: AudioBudgetLimits,
    ) -> tuple[bool, str | None]:
        now = self._now_utc()
        minute_key = now.strftime("%Y-%m-%dT%H:%M")
        day_key = now.strftime("%Y-%m-%d")
        month_key = now.strftime("%Y-%m")

        if limits.max_requests_per_minute is not None:
            current_rpm = self._get_usage(provider_id, "minute", minute_key)
            if current_rpm["request_count"] >= limits.max_requests_per_minute:
                return (
                    False,
                    f"Rate limit exceeded: {current_rpm['request_count']}/{limits.max_requests_per_minute} requests per minute",
                )

        if limits.max_chars_per_day is not None:
            current_day = self._get_usage(provider_id, "day", day_key)
            if current_day["char_count"] + char_count > limits.max_chars_per_day:
                return (
                    False,
                    f"Daily limit exceeded: {current_day['char_count'] + char_count}/{limits.max_chars_per_day} chars",
                )

        if limits.max_requests_per_day is not None:
            current_day = self._get_usage(provider_id, "day", day_key)
            if current_day["request_count"] >= limits.max_requests_per_day:
                return (
                    False,
                    f"Daily request limit exceeded: {current_day['request_count']}/{limits.max_requests_per_day} requests",
                )

        if limits.max_chars_per_month is not None:
            current_month = self._get_usage(provider_id, "month", month_key)
            if current_month["char_count"] + char_count > limits.max_chars_per_month:
                return (
                    False,
                    f"Monthly limit exceeded: {current_month['char_count'] + char_count}/{limits.max_chars_per_month} chars",
                )

        return (True, None)

    def record_spend(
        self,
        provider_id: str,
        char_count: int,
        request_count: int = 1,
        timestamp_utc: datetime | None = None,
        commit: bool = True,
    ) -> None:
        now = timestamp_utc or self._now_utc()
        minute_key = now.strftime("%Y-%m-%dT%H:%M")
        day_key = now.strftime("%Y-%m-%d")
        month_key = now.strftime("%Y-%m")

        self.record_spend_for_keys(
            provider_id=provider_id,
            minute_key=minute_key,
            day_key=day_key,
            month_key=month_key,
            char_count=char_count,
            request_count=request_count,
            commit=commit,
        )

    def record_spend_for_keys(
        self,
        provider_id: str,
        minute_key: str,
        day_key: str,
        month_key: str,
        char_count: int,
        request_count: int = 1,
        commit: bool = True,
    ) -> None:
        self._record_period(provider_id, "minute", minute_key, char_count, request_count)
        self._record_period(provider_id, "day", day_key, char_count, request_count)
        self._record_period(provider_id, "month", month_key, char_count, request_count)

        if commit:
            self.session.commit()

    def _get_usage(
        self,
        provider_id: str,
        period_type: str,
        period_key: str,
    ) -> dict:
        query = text(
            """
            SELECT char_count, request_count
            FROM audio_usage
            WHERE provider_id = :provider_id
              AND period_type = :period_type
              AND period_key = :period_key
            """
        )

        result = self.session.execute(
            query,
            {
                "provider_id": provider_id,
                "period_type": period_type,
                "period_key": period_key,
            },
        ).fetchone()

        if result:
            return {"char_count": int(result[0]), "request_count": int(result[1])}
        return {"char_count": 0, "request_count": 0}

    def _record_period(
        self,
        provider_id: str,
        period_type: str,
        period_key: str,
        char_count: int,
        request_count: int,
    ) -> None:
        query = text(
            """
            INSERT INTO audio_usage (provider_id, period_type, period_key, char_count, request_count)
            VALUES (:provider_id, :period_type, :period_key, :char_count, :request_count)
            ON CONFLICT(provider_id, period_type, period_key)
            DO UPDATE SET
                char_count = char_count + :char_count,
                request_count = request_count + :request_count,
                updated_at = datetime('now')
            """
        )

        self.session.execute(
            query,
            {
                "provider_id": provider_id,
                "period_type": period_type,
                "period_key": period_key,
                "char_count": int(char_count),
                "request_count": int(request_count),
            },
        )

    def get_usage_summary(self, provider_id: str) -> dict:
        now = self._now_utc()
        minute_key = now.strftime("%Y-%m-%dT%H:%M")
        day_key = now.strftime("%Y-%m-%d")
        month_key = now.strftime("%Y-%m")

        return {
            "minute": self._get_usage(provider_id, "minute", minute_key),
            "day": self._get_usage(provider_id, "day", day_key),
            "month": self._get_usage(provider_id, "month", month_key),
        }
