"""MT Usage Tracker - Budget guard enforcement.

Tracks usage by provider and time period (minute/day/month).
Provides atomic can_spend() and record_spend() operations for concurrent access.
"""

import logging
from datetime import datetime
from typing import Optional, Tuple
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.infra.translators.provider_config import ProviderLimitsConfig

logger = logging.getLogger(__name__)


class MTUsageTracker:
    """Tracks MT provider usage for budget guard enforcement."""

    def __init__(self, session: Session):
        """Initialize tracker with DB session.

        Args:
            session: SQLAlchemy session for database access
        """
        self.session = session

    def can_spend(
        self,
        provider_id: str,
        char_count: int,
        limits: ProviderLimitsConfig,
    ) -> Tuple[bool, Optional[str]]:
        """Check if spending is allowed based on budget limits.

        Args:
            provider_id: Provider identifier (e.g., "google_cloud_translate")
            char_count: Number of characters to spend
            limits: Provider limits configuration

        Returns:
            Tuple of (allowed: bool, error_message: Optional[str])
            - (True, None) if spending allowed
            - (False, error_message) if budget limit would be exceeded
        """
        # Get current usage for all relevant periods
        now = datetime.utcnow()
        minute_key = now.strftime("%Y-%m-%dT%H:%M")
        day_key = now.strftime("%Y-%m-%d")
        month_key = now.strftime("%Y-%m")

        # Check requests per minute
        if limits.max_requests_per_minute is not None:
            current_rpm = self._get_usage(provider_id, "minute", minute_key)
            if current_rpm["request_count"] >= limits.max_requests_per_minute:
                return (
                    False,
                    f"Rate limit exceeded: {current_rpm['request_count']}/{limits.max_requests_per_minute} requests per minute",
                )

        # Check chars per day
        if limits.max_chars_per_day is not None:
            current_day = self._get_usage(provider_id, "day", day_key)
            if current_day["char_count"] + char_count > limits.max_chars_per_day:
                return (
                    False,
                    f"Daily limit exceeded: {current_day['char_count'] + char_count}/{limits.max_chars_per_day} chars",
                )

        # Check requests per day
        if limits.max_requests_per_day is not None:
            current_day = self._get_usage(provider_id, "day", day_key)
            if current_day["request_count"] >= limits.max_requests_per_day:
                return (
                    False,
                    f"Daily request limit exceeded: {current_day['request_count']}/{limits.max_requests_per_day} requests",
                )

        # Check chars per month
        if limits.max_chars_per_month is not None:
            current_month = self._get_usage(provider_id, "month", month_key)
            if current_month["char_count"] + char_count > limits.max_chars_per_month:
                return (
                    False,
                    f"Monthly limit exceeded: {current_month['char_count'] + char_count}/{limits.max_chars_per_month} chars",
                )

        # All checks passed
        return (True, None)

    def record_spend(
        self,
        provider_id: str,
        char_count: int,
        request_count: int = 1,
        timestamp_utc: Optional[datetime] = None,
        commit: bool = True,
    ) -> None:
        """Record usage atomically.

        Uses INSERT ... ON CONFLICT DO UPDATE for atomic increments.

        Args:
            provider_id: Provider identifier
            char_count: Number of characters spent
            request_count: Number of requests made (default: 1)
            timestamp_utc: Optional UTC timestamp bucket source
            commit: Whether to commit session after write
        """
        now = timestamp_utc or datetime.utcnow()
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
        """Record usage using explicit period keys.

        Useful for deferred/retry flows that must preserve original time buckets.
        """

        # Record usage for all periods
        self._record_period(provider_id, "minute", minute_key, char_count, request_count)
        self._record_period(provider_id, "day", day_key, char_count, request_count)
        self._record_period(provider_id, "month", month_key, char_count, request_count)

        if commit:
            self.session.commit()

        logger.debug(
            f"[{provider_id}] Recorded usage: {char_count} chars, {request_count} requests"
        )

    def _get_usage(
        self,
        provider_id: str,
        period_type: str,
        period_key: str,
    ) -> dict:
        """Get current usage for a period.

        Args:
            provider_id: Provider identifier
            period_type: 'minute', 'day', or 'month'
            period_key: Period key (e.g., '2026-02-08T15:30')

        Returns:
            dict with 'char_count' and 'request_count' keys (0 if not found)
        """
        query = text(
            """
            SELECT char_count, request_count
            FROM mt_usage
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
            return {"char_count": result[0], "request_count": result[1]}
        else:
            return {"char_count": 0, "request_count": 0}

    def _record_period(
        self,
        provider_id: str,
        period_type: str,
        period_key: str,
        char_count: int,
        request_count: int,
    ) -> None:
        """Record usage for a specific period (atomic).

        Uses INSERT ... ON CONFLICT DO UPDATE for atomic increments.

        Args:
            provider_id: Provider identifier
            period_type: 'minute', 'day', or 'month'
            period_key: Period key
            char_count: Characters to add
            request_count: Requests to add
        """
        query = text(
            """
            INSERT INTO mt_usage (provider_id, period_type, period_key, char_count, request_count)
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
                "char_count": char_count,
                "request_count": request_count,
            },
        )

    def get_usage_summary(self, provider_id: str) -> dict:
        """Get current usage summary for a provider.

        Args:
            provider_id: Provider identifier

        Returns:
            dict with current minute/day/month usage
        """
        now = datetime.utcnow()
        minute_key = now.strftime("%Y-%m-%dT%H:%M")
        day_key = now.strftime("%Y-%m-%d")
        month_key = now.strftime("%Y-%m")

        return {
            "minute": self._get_usage(provider_id, "minute", minute_key),
            "day": self._get_usage(provider_id, "day", day_key),
            "month": self._get_usage(provider_id, "month", month_key),
        }
