-- Migration 021: Audio usage tracking for budget guards
-- Date: 2026-02-19
-- Purpose:
--   1) Track audio provider usage per minute/day/month buckets
--   2) Enable fail-closed budget guards in audio generation pipeline

CREATE TABLE IF NOT EXISTS audio_usage (
    usage_id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id TEXT NOT NULL,
    period_type TEXT NOT NULL,  -- minute | day | month
    period_key TEXT NOT NULL,   -- YYYY-MM-DDTHH:MM | YYYY-MM-DD | YYYY-MM
    char_count INTEGER NOT NULL DEFAULT 0,
    request_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(provider_id, period_type, period_key),
    CHECK(period_type IN ('minute', 'day', 'month'))
);

CREATE INDEX IF NOT EXISTS idx_audio_usage_lookup
    ON audio_usage(provider_id, period_type, period_key);

UPDATE schema_meta SET value = '21' WHERE key = 'schema_version';
