-- P2.3: Add 'revert' to allowed origin values for TM entries
-- Schema version: 5 → 6

-- Drop old constraint and add new one with 'revert'
-- SQLite doesn't support ALTER TABLE ... DROP CONSTRAINT, so we need to recreate the table

PRAGMA foreign_keys = OFF;

BEGIN TRANSACTION;

-- Create new table with updated CHECK constraint
CREATE TABLE tm_entry_new (
    tm_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NULL,
    kind TEXT NOT NULL CHECK(kind IN ('lemma', 'ngram', 'term_cluster', 'surface')),
    src_lang TEXT NOT NULL,
    tgt_lang TEXT NOT NULL,
    src_text TEXT NOT NULL,
    src_norm TEXT NOT NULL,
    translation TEXT NOT NULL,
    translation_norm TEXT NULL,
    pos TEXT NULL,
    domain TEXT NULL,
    notes TEXT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft', 'approved', 'rejected', 'deprecated')),
    confidence REAL NULL CHECK(confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    origin TEXT NOT NULL CHECK(origin IN ('user_edit', 'import', 'mt_accept', 'mt_auto', 'merge', 'revert')),
    source_ref TEXT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    approved_at TEXT NULL,
    approved_by TEXT NULL,

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
CREATE INDEX IF NOT EXISTS idx_tm_entry_lookup
    ON tm_entry(project_id, status, kind);

CREATE INDEX IF NOT EXISTS idx_tm_entry_src_norm
    ON tm_entry(src_norm);

CREATE INDEX IF NOT EXISTS idx_tm_entry_translation_norm
    ON tm_entry(translation_norm);

-- Update schema version
UPDATE schema_meta SET value = '6' WHERE key = 'schema_version';

COMMIT;

PRAGMA foreign_keys = ON;

-- Verify
SELECT key, value FROM schema_meta WHERE key = 'schema_version';
