-- Migration 020: Pronunciation dictionary (local layer)
-- Date: 2026-02-19
-- Purpose:
--   1) Add pronunciation_entry table for niqqud/IPA overrides
--   2) Support auto bootstrap + manual overrides (manual wins)

CREATE TABLE IF NOT EXISTS pronunciation_entry (
    entry_id INTEGER PRIMARY KEY,
    lang TEXT NOT NULL,
    src_norm TEXT NOT NULL,
    niqqud_text TEXT,
    ipa TEXT,
    source TEXT NOT NULL DEFAULT 'auto',
    is_override INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(lang, src_norm),
    CHECK(source IN ('auto', 'manual')),
    CHECK(is_override IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_pronunciation_lang_norm
    ON pronunciation_entry(lang, src_norm);

CREATE INDEX IF NOT EXISTS idx_pronunciation_source
    ON pronunciation_entry(source, is_override);

UPDATE schema_meta SET value = '20' WHERE key = 'schema_version';
