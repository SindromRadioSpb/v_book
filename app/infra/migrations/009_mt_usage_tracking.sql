-- Migration 009: MT Usage Tracking
-- Date: 2026-02-08
-- Purpose: Track MT provider usage for budget guard enforcement

-- mt_usage: Usage tracking by provider and time period
CREATE TABLE IF NOT EXISTS mt_usage (
    usage_id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id TEXT NOT NULL,
    period_type TEXT NOT NULL,  -- 'minute', 'day', 'month'
    period_key TEXT NOT NULL,   -- '2026-02-08T15:30', '2026-02-08', '2026-02'
    char_count INTEGER NOT NULL DEFAULT 0,
    request_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(provider_id, period_type, period_key)
);

-- Index for efficient lookups by provider and period
CREATE INDEX IF NOT EXISTS idx_mt_usage_lookup ON mt_usage(provider_id, period_type, period_key);

-- Update schema version
UPDATE schema_meta SET value = '9' WHERE key = 'schema_version';
