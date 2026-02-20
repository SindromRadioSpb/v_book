-- Migration 022: Pronunciation layer v2 (reading/source/confidence)
-- Date: 2026-02-20
-- Purpose:
--   1) Extend pronunciation_entry with reading_text and confidence
--   2) Expand source semantics for auto bootstrap/import channels
--   3) Keep UNIQUE(lang, src_norm) and manual-wins merge compatibility

CREATE TABLE IF NOT EXISTS pronunciation_entry_v2 (
    entry_id INTEGER PRIMARY KEY,
    lang TEXT NOT NULL,
    src_norm TEXT NOT NULL,
    niqqud_text TEXT,
    ipa TEXT,
    reading_text TEXT,
    source TEXT NOT NULL DEFAULT 'manual',
    confidence REAL,
    is_override INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(lang, src_norm),
    CHECK(source IN ('manual', 'auto', 'auto_phonikud', 'import_csv', 'import_pls')),
    CHECK(is_override IN (0, 1)),
    CHECK(confidence IS NULL OR (confidence >= 0 AND confidence <= 1))
);

INSERT INTO pronunciation_entry_v2 (
    entry_id,
    lang,
    src_norm,
    niqqud_text,
    ipa,
    reading_text,
    source,
    confidence,
    is_override,
    notes,
    created_at,
    updated_at
)
SELECT
    entry_id,
    lang,
    src_norm,
    niqqud_text,
    ipa,
    NULL AS reading_text,
    CASE
        WHEN source IN ('manual', 'auto', 'auto_phonikud', 'import_csv', 'import_pls') THEN source
        ELSE 'manual'
    END AS source,
    NULL AS confidence,
    is_override,
    notes,
    created_at,
    updated_at
FROM pronunciation_entry;

DROP TABLE pronunciation_entry;
ALTER TABLE pronunciation_entry_v2 RENAME TO pronunciation_entry;

CREATE UNIQUE INDEX IF NOT EXISTS uq_pronunciation_entry_key
    ON pronunciation_entry(lang, src_norm);
CREATE INDEX IF NOT EXISTS idx_pronunciation_lang_norm
    ON pronunciation_entry(lang, src_norm);
CREATE INDEX IF NOT EXISTS idx_pronunciation_source
    ON pronunciation_entry(source, is_override);

UPDATE schema_meta SET value = '22' WHERE key = 'schema_version';
