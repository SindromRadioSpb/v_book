-- Migration 038: sentence NLP snapshots
-- Date: 2026-03-09
-- Purpose:
--   1) persist sentence-level NLP token/POS/lemma snapshots during processing
--   2) let term extraction reuse processed NLP output instead of reparsing text
--   3) keep snapshots tied to document_sentence lifecycle via ON DELETE CASCADE

CREATE TABLE IF NOT EXISTS sentence_nlp_snapshot (
  sentence_id INTEGER PRIMARY KEY
    REFERENCES document_sentence(sentence_id) ON DELETE CASCADE,
  engine TEXT NOT NULL,
  engine_version TEXT,
  sentence_text_hash TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  token_count INTEGER NOT NULL DEFAULT 0 CHECK(token_count >= 0),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_sentence_nlp_snapshot_engine
  ON sentence_nlp_snapshot(engine, engine_version);

UPDATE schema_meta SET value = '38' WHERE key = 'schema_version';
