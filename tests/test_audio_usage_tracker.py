"""Tests for audio usage tracker budget guards."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.services.audio_usage_tracker import AudioBudgetLimits, AudioUsageTracker


CREATE_AUDIO_USAGE_SQL = """
CREATE TABLE IF NOT EXISTS audio_usage (
    usage_id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id TEXT NOT NULL,
    period_type TEXT NOT NULL,
    period_key TEXT NOT NULL,
    char_count INTEGER NOT NULL DEFAULT 0,
    request_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(provider_id, period_type, period_key)
)
"""


def _create_audio_usage_table(session: Session) -> None:
    session.execute(text(CREATE_AUDIO_USAGE_SQL))
    session.commit()


def _workspace_temp_dir(prefix: str) -> Path:
    root = Path("build") / "tmp_tests"
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=str(root)))


def test_audio_usage_tracker_records_and_summarizes_usage():
    temp_dir = _workspace_temp_dir("audio_usage_summary_")
    engine = create_engine(f"sqlite:///{temp_dir / 'audio_usage.db'}")
    try:
        with Session(engine) as session:
            _create_audio_usage_table(session)
            tracker = AudioUsageTracker(session)

            tracker.record_spend("google_cloud_tts", char_count=12, request_count=1)
            summary = tracker.get_usage_summary("google_cloud_tts")

            assert summary["minute"]["char_count"] == 12
            assert summary["minute"]["request_count"] == 1
            assert summary["day"]["char_count"] == 12
            assert summary["month"]["request_count"] == 1
    finally:
        engine.dispose()
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_audio_usage_tracker_enforces_limits():
    temp_dir = _workspace_temp_dir("audio_usage_limits_")
    engine = create_engine(f"sqlite:///{temp_dir / 'audio_limits.db'}")
    try:
        with Session(engine) as session:
            _create_audio_usage_table(session)
            tracker = AudioUsageTracker(session)

            limits = AudioBudgetLimits(
                max_chars_per_request=1000,
                max_requests_per_minute=1,
                max_chars_per_day=20,
                max_chars_per_month=40,
                max_requests_per_day=2,
                fail_closed=True,
            )

            allowed, err = tracker.can_spend("azure_speech_tts", char_count=15, limits=limits)
            assert allowed is True
            assert err is None

            tracker.record_spend("azure_speech_tts", char_count=15, request_count=1)

            allowed2, err2 = tracker.can_spend("azure_speech_tts", char_count=10, limits=limits)
            assert allowed2 is False
            assert err2 is not None
            assert "limit" in err2.lower()
    finally:
        engine.dispose()
        shutil.rmtree(temp_dir, ignore_errors=True)
