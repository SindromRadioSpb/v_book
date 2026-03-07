-- Migration 031: denormalize corpus_id into document_sentence for fast pagination
-- Date: 2026-03-07
--
-- Root cause: list_sentences() page query takes ~584 s on hewiki (13 M rows)
-- because the 3-table JOIN (document_sentence → source_document → source_corpus)
-- with ORDER BY sentence_id LIMIT 100 forces a TEMP B-TREE sort over all 13 M rows.
--
-- Fix: add corpus_id directly on document_sentence so the query can use a
-- covering index (corpus_id, sentence_id) for O(page_size) pagination.
--
--   BEFORE: TEMP B-TREE on 13 M rows → ~584 s
--   AFTER:  covering index scan (corpus_id, sentence_id) → <5 ms
--
-- Backfill: single UPDATE over 13 M rows — one-time cost (~30–120 s on hewiki).
-- Migration runner handles "duplicate column name" if re-applied.

ALTER TABLE document_sentence ADD COLUMN corpus_id INTEGER REFERENCES source_corpus(corpus_id);

-- Backfill: one-time, acceptable migration cost
UPDATE document_sentence
    SET corpus_id = (
        SELECT sd.corpus_id
        FROM source_document sd
        WHERE sd.doc_id = document_sentence.doc_id
    );

-- Covering index: enables O(page_size) scan for paginated sentence listing
CREATE INDEX IF NOT EXISTS idx_sentence_corpus_sent_id
    ON document_sentence(corpus_id, sentence_id);

UPDATE schema_meta SET value = '31' WHERE key = 'schema_version';
