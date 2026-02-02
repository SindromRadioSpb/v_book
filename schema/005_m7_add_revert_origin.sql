-- M7: Add 'revert' to allowed origin values in tm_entry
-- Schema Version: 5 → 6
-- Date: 2026-02-02

-- Drop existing CHECK constraint and recreate with 'revert'
-- SQLite doesn't support ALTER TABLE ... DROP CONSTRAINT, so we need to recreate table

PRAGMA foreign_keys = OFF;

BEGIN TRANSACTION;

-- Create new tm_entry table with updated constraint
CREATE TABLE tm_entry_new (
    tm_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NULL,
    kind TEXT NOT NULL CHECK(kind IN ('lemma', 'ngram', 'term_cluster', 'surface')),
    src_lang TEXT NOT NULL,
    tgt_lang TEXT NOT NULL,
    src_text TEXT NOT NULL,
    src_norm TEXT NOT NULL,
    translation TEXT NOT NULL,
    translation_norm TEXT,
    pos TEXT,
    domain TEXT,
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft', 'approved', 'rejected', 'deprecated')),
    confidence REAL,
    -- UPDATED: Added 'revert' to allowed origins
    origin TEXT NOT NULL CHECK(origin IN ('user_edit', 'import', 'mt_accept', 'mt_auto', 'merge', 'revert')),
    source_ref TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
    approved_at TEXT,
    approved_by TEXT,
    FOREIGN KEY (project_id) REFERENCES dict_project(project_id) ON DELETE CASCADE,
    UNIQUE (project_id, kind, src_lang, tgt_lang, src_norm)
);

-- Copy data from old table
INSERT INTO tm_entry_new SELECT * FROM tm_entry;

-- Drop old table
DROP TABLE tm_entry;

-- Rename new table
ALTER TABLE tm_entry_new RENAME TO tm_entry;

-- Recreate indexes
CREATE INDEX IF NOT EXISTS idx_tm_entry_lookup ON tm_entry(project_id, kind, src_lang, tgt_lang, src_norm, status);
CREATE INDEX IF NOT EXISTS idx_tm_entry_src_norm ON tm_entry(src_norm);
CREATE INDEX IF NOT EXISTS idx_tm_entry_translation_norm ON tm_entry(translation_norm);
CREATE INDEX IF NOT EXISTS idx_tm_lookup_lemma ON tm_entry(src_lang, tgt_lang, kind, src_norm) WHERE kind = 'lemma';
CREATE INDEX IF NOT EXISTS idx_tm_lookup_ngram ON tm_entry(src_lang, tgt_lang, kind, src_norm) WHERE kind = 'ngram';

-- Update schema version
UPDATE schema_meta SET value = '6' WHERE key = 'schema_version';

COMMIT;

PRAGMA foreign_keys = ON;
