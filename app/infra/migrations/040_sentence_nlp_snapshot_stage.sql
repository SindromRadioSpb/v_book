-- Migration 040: staged sentence snapshot backfill
-- Date: 2026-03-10
-- Purpose:
--   1) stage large legacy sentence_nlp_snapshot backfill writes outside the
--      final target table
--   2) support bounded merge batches into sentence_nlp_snapshot
--   3) let resumable backfill discard incomplete super-chunks safely

CREATE TABLE IF NOT EXISTS sentence_nlp_snapshot_stage (
  run_id INTEGER NOT NULL
    REFERENCES processor_run(run_id) ON DELETE CASCADE,
  sentence_id INTEGER NOT NULL
    REFERENCES document_sentence(sentence_id) ON DELETE CASCADE,
  engine TEXT NOT NULL,
  engine_version TEXT,
  sentence_text_hash TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  token_count INTEGER NOT NULL DEFAULT 0 CHECK(token_count >= 0),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  PRIMARY KEY (run_id, sentence_id)
);

CREATE INDEX IF NOT EXISTS idx_sentence_nlp_snapshot_stage_sentence
  ON sentence_nlp_snapshot_stage(sentence_id);

UPDATE schema_meta SET value = '40' WHERE key = 'schema_version';
