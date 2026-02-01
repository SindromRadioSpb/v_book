-- Migration 004: Concordance performance optimization
-- Adds index for fast project-based filtering in concordance/KWIC search

-- =================================================================
-- 1. Add composite index for project filtering via corpus
-- =================================================================

-- For concordance queries that filter by project_id:
-- SELECT ... FROM sentence_fts
--   JOIN document_sentence ds ON ds.sentence_id = sentence_fts.rowid
--   JOIN source_document sd ON sd.doc_id = ds.doc_id
--   JOIN source_corpus sc ON sc.corpus_id = sd.corpus_id
--   WHERE sc.project_id = ?
--
-- This index speeds up the JOIN from source_document → source_corpus
CREATE INDEX IF NOT EXISTS idx_doc_corpus FOR project ON source_document(corpus_id, doc_id);

-- Alternative: if we add project_id denormalized to source_document later,
-- this would be faster, but for now we use the join approach

-- =================================================================
-- 2. Update schema version
-- =================================================================

UPDATE schema_meta SET value = '4' WHERE key = 'schema_version';

-- =================================================================
-- Migration 004 complete
-- =================================================================
