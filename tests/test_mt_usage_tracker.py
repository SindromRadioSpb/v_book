"""Unit tests for MT Usage Tracker.

Tests:
- can_spend() budget guard enforcement
- record_spend() atomic updates
- Concurrent access handling
- Usage summary retrieval
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, patch
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

from app.services.mt_usage_tracker import MTUsageTracker
from app.infra.translators.provider_config import ProviderLimitsConfig


@pytest.fixture
def in_memory_session():
    """Create in-memory SQLite session for testing."""
    engine = create_engine("sqlite:///:memory:")

    # Create mt_usage table
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE mt_usage (
                usage_id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider_id TEXT NOT NULL,
                period_type TEXT NOT NULL,
                period_key TEXT NOT NULL,
                char_count INTEGER NOT NULL DEFAULT 0,
                request_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(provider_id, period_type, period_key)
            )
        """))
        conn.commit()

    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    yield session

    session.close()


class TestCanSpend:
    """Test can_spend() budget guard enforcement."""

    def test_no_limits_always_allowed(self, in_memory_session):
        """Test spending allowed when no limits configured."""
        tracker = MTUsageTracker(in_memory_session)
        limits = ProviderLimitsConfig()  # No day/month limits

        allowed, error_msg = tracker.can_spend("test_provider", 1000, limits)

        assert allowed is True
        assert error_msg is None

    def test_chars_per_day_limit_enforced(self, in_memory_session):
        """Test chars per day limit enforced."""
        tracker = MTUsageTracker(in_memory_session)
        limits = ProviderLimitsConfig(max_chars_per_day=1000)

        # First request: 800 chars (allowed)
        allowed, _ = tracker.can_spend("test_provider", 800, limits)
        assert allowed is True

        # Record usage
        tracker.record_spend("test_provider", 800, 1)

        # Second request: 300 chars (would exceed 1000) (denied)
        allowed, error_msg = tracker.can_spend("test_provider", 300, limits)
        assert allowed is False
        assert "Daily limit exceeded" in error_msg
        assert "1100/1000" in error_msg

    def test_chars_per_month_limit_enforced(self, in_memory_session):
        """Test chars per month limit enforced."""
        tracker = MTUsageTracker(in_memory_session)
        limits = ProviderLimitsConfig(max_chars_per_month=5000)

        # Record 4500 chars
        tracker.record_spend("test_provider", 4500, 1)

        # Request 600 chars (would exceed 5000)
        allowed, error_msg = tracker.can_spend("test_provider", 600, limits)
        assert allowed is False
        assert "Monthly limit exceeded" in error_msg
        assert "5100/5000" in error_msg

    def test_requests_per_minute_limit_enforced(self, in_memory_session):
        """Test requests per minute limit enforced."""
        tracker = MTUsageTracker(in_memory_session)
        limits = ProviderLimitsConfig(max_requests_per_minute=3)

        # Record 3 requests
        tracker.record_spend("test_provider", 100, 1)
        tracker.record_spend("test_provider", 100, 1)
        tracker.record_spend("test_provider", 100, 1)

        # 4th request in same minute (denied)
        allowed, error_msg = tracker.can_spend("test_provider", 100, limits)
        assert allowed is False
        assert "Rate limit exceeded" in error_msg
        assert "3/3 requests per minute" in error_msg

    def test_requests_per_day_limit_enforced(self, in_memory_session):
        """Test requests per day limit enforced."""
        tracker = MTUsageTracker(in_memory_session)
        limits = ProviderLimitsConfig(max_requests_per_day=10)

        # Record 10 requests
        for _ in range(10):
            tracker.record_spend("test_provider", 50, 1)

        # 11th request (denied)
        allowed, error_msg = tracker.can_spend("test_provider", 50, limits)
        assert allowed is False
        assert "Daily request limit exceeded" in error_msg
        assert "10/10" in error_msg


class TestRecordSpend:
    """Test record_spend() atomic updates."""

    def test_record_spend_creates_new_row(self, in_memory_session):
        """Test first spend creates new row."""
        tracker = MTUsageTracker(in_memory_session)

        tracker.record_spend("test_provider", 100, 1)

        # Verify usage recorded
        summary = tracker.get_usage_summary("test_provider")
        assert summary["day"]["char_count"] == 100
        assert summary["day"]["request_count"] == 1

    def test_record_spend_increments_existing_row(self, in_memory_session):
        """Test subsequent spends increment existing row."""
        tracker = MTUsageTracker(in_memory_session)

        # First spend
        tracker.record_spend("test_provider", 100, 1)

        # Second spend
        tracker.record_spend("test_provider", 200, 1)

        # Verify cumulative usage
        summary = tracker.get_usage_summary("test_provider")
        assert summary["day"]["char_count"] == 300
        assert summary["day"]["request_count"] == 2

    def test_record_spend_all_periods(self, in_memory_session):
        """Test spend recorded for minute/day/month."""
        tracker = MTUsageTracker(in_memory_session)

        tracker.record_spend("test_provider", 100, 1)

        summary = tracker.get_usage_summary("test_provider")

        # All periods should have same usage
        assert summary["minute"]["char_count"] == 100
        assert summary["day"]["char_count"] == 100
        assert summary["month"]["char_count"] == 100


class TestConcurrentAccess:
    """Test concurrent access handling."""

    def test_concurrent_spends_atomic(self, in_memory_session):
        """Test concurrent spends are atomic (no race condition)."""
        tracker = MTUsageTracker(in_memory_session)

        # Simulate 5 concurrent spends
        for _ in range(5):
            tracker.record_spend("test_provider", 100, 1)

        # Verify total usage (should be exactly 500, not less due to race)
        summary = tracker.get_usage_summary("test_provider")
        assert summary["day"]["char_count"] == 500
        assert summary["day"]["request_count"] == 5


class TestUsageSummary:
    """Test get_usage_summary()."""

    def test_usage_summary_empty(self, in_memory_session):
        """Test summary returns zeros for new provider."""
        tracker = MTUsageTracker(in_memory_session)

        summary = tracker.get_usage_summary("new_provider")

        assert summary["minute"]["char_count"] == 0
        assert summary["day"]["char_count"] == 0
        assert summary["month"]["char_count"] == 0

    def test_usage_summary_with_data(self, in_memory_session):
        """Test summary returns actual usage."""
        tracker = MTUsageTracker(in_memory_session)

        tracker.record_spend("test_provider", 1000, 5)

        summary = tracker.get_usage_summary("test_provider")

        assert summary["day"]["char_count"] == 1000
        assert summary["day"]["request_count"] == 5


class TestMultipleProviders:
    """Test isolation between providers."""

    def test_providers_isolated(self, in_memory_session):
        """Test different providers have isolated usage."""
        tracker = MTUsageTracker(in_memory_session)

        # Record usage for provider A
        tracker.record_spend("provider_a", 100, 1)

        # Record usage for provider B
        tracker.record_spend("provider_b", 200, 1)

        # Verify isolation
        summary_a = tracker.get_usage_summary("provider_a")
        summary_b = tracker.get_usage_summary("provider_b")

        assert summary_a["day"]["char_count"] == 100
        assert summary_b["day"]["char_count"] == 200
