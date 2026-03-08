-- Migration 034: backfill document_sentence.corpus_id for rows created after
-- migration 031 but before ProcessService started writing the denormalized value.

UPDATE document_sentence
SET corpus_id = (
    SELECT sd.corpus_id
    FROM source_document sd
    WHERE sd.doc_id = document_sentence.doc_id
)
WHERE corpus_id IS NULL;

UPDATE schema_meta SET value = '34' WHERE key = 'schema_version';
