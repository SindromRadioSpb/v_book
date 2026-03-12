BEGIN;

ALTER TABLE source_document
    ADD COLUMN snapshot_sentence_count INTEGER NOT NULL DEFAULT 0;

ALTER TABLE source_document
    ADD COLUMN snapshot_stats_state TEXT NOT NULL DEFAULT 'unknown';

ALTER TABLE source_document
    ADD COLUMN snapshot_stats_updated_at TEXT;

CREATE INDEX IF NOT EXISTS idx_doc_corpus_status_snapshot_state
    ON source_document(corpus_id, status, snapshot_stats_state);

UPDATE schema_meta
SET value = '42'
WHERE key = 'schema_version';

COMMIT;
