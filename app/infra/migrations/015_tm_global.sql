-- Migration 015: tm_global canonical translation layer
-- Date: 2026-02-13
-- Purpose: Cross-project canonical translations

-- Create tm_global table
CREATE TABLE IF NOT EXISTS tm_global (
    tm_global_id  INTEGER PRIMARY KEY,
    src_lang      TEXT    NOT NULL,
    tgt_lang      TEXT    NOT NULL,
    kind          TEXT    NOT NULL,  -- lemma|ngram|term_cluster|surface
    src_norm      TEXT    NOT NULL,
    src_text      TEXT    NOT NULL,
    translation   TEXT    NOT NULL DEFAULT '',
    status        TEXT    NOT NULL DEFAULT 'draft',
    origin        TEXT    NOT NULL DEFAULT 'mt_auto',
    confidence    REAL,
    is_noise      INTEGER DEFAULT 0,
    noise_reason  TEXT,
    notes         TEXT,
    source_tm_id  INTEGER,  -- tm_entry.tm_id that "won" the merge
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    updated_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),

    CONSTRAINT uq_tm_global UNIQUE (src_lang, tgt_lang, kind, src_norm),
    CONSTRAINT ck_tmg_kind CHECK (kind IN ('lemma', 'ngram', 'term_cluster', 'surface')),
    CONSTRAINT ck_tmg_status CHECK (status IN ('draft', 'approved', 'rejected', 'deprecated')),
    CONSTRAINT ck_tmg_origin CHECK (origin IN ('user_edit', 'import', 'mt_accept', 'mt_auto', 'merge', 'revert'))
);

-- Add foreign key column to tm_entry
ALTER TABLE tm_entry ADD COLUMN tm_global_id INTEGER REFERENCES tm_global(tm_global_id) ON DELETE SET NULL;

-- Indexes for fast lookups
CREATE INDEX IF NOT EXISTS idx_tm_global_lookup ON tm_global(src_lang, tgt_lang, kind, src_norm);
CREATE INDEX IF NOT EXISTS idx_tm_entry_global_id ON tm_entry(tm_global_id);

-- Update schema version
UPDATE schema_meta SET value = '15' WHERE key = 'schema_version';
