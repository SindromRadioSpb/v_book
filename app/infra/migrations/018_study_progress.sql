-- Migration 018: Global study_progress (SM-2) + per-item suspension
-- Date: 2026-02-18
-- Purpose:
--   1) Add global SRS progress by canonical_hash
--   2) Add per-item suspension in user_dictionary_item
--   3) Backfill progress rows for existing user dictionary items

-- ---------------------------------------------------------------------------
-- Global study progress
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS study_progress (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_hash TEXT NOT NULL UNIQUE,
    first_seen_at  TEXT NOT NULL,
    last_review_at TEXT,
    due_at         TEXT NOT NULL,
    review_count   INTEGER NOT NULL DEFAULT 0,
    lapse_count    INTEGER NOT NULL DEFAULT 0,
    interval_days  INTEGER NOT NULL DEFAULT 0,
    ease_factor    REAL NOT NULL DEFAULT 2.5,
    last_quality   INTEGER,
    updated_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_study_progress_due_at ON study_progress(due_at);
CREATE INDEX IF NOT EXISTS idx_study_progress_review_count ON study_progress(review_count);

-- ---------------------------------------------------------------------------
-- Per-item suspension and progress link
-- ---------------------------------------------------------------------------
ALTER TABLE user_dictionary_item ADD COLUMN study_progress_id INTEGER REFERENCES study_progress(id) ON DELETE SET NULL;
ALTER TABLE user_dictionary_item ADD COLUMN is_suspended INTEGER NOT NULL DEFAULT 0 CHECK(is_suspended IN (0, 1));
ALTER TABLE user_dictionary_item ADD COLUMN suspended_reason TEXT;

CREATE INDEX IF NOT EXISTS idx_udi_progress ON user_dictionary_item(study_progress_id);
CREATE INDEX IF NOT EXISTS idx_udi_dict_suspended ON user_dictionary_item(dictionary_id, is_suspended);

-- ---------------------------------------------------------------------------
-- Backfill study_progress for existing dictionary items
-- ---------------------------------------------------------------------------
INSERT OR IGNORE INTO study_progress (
    canonical_hash,
    first_seen_at,
    due_at,
    review_count,
    lapse_count,
    interval_days,
    ease_factor,
    updated_at
)
SELECT
    udi.canonical_hash,
    COALESCE(MIN(udi.created_at), strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    COALESCE(MIN(udi.created_at), strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    0,
    0,
    0,
    2.5,
    COALESCE(MAX(udi.updated_at), strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
FROM user_dictionary_item udi
GROUP BY udi.canonical_hash;

UPDATE user_dictionary_item
SET study_progress_id = (
    SELECT sp.id
    FROM study_progress sp
    WHERE sp.canonical_hash = user_dictionary_item.canonical_hash
)
WHERE study_progress_id IS NULL;

-- ---------------------------------------------------------------------------
-- Schema version
-- ---------------------------------------------------------------------------
UPDATE schema_meta SET value = '18' WHERE key = 'schema_version';

