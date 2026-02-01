-- Migration 003: Add per-document NLP metrics
-- Adds sentence_count and token_count columns to source_document table
-- for displaying NLP processing results in Documents UI

-- =================================================================
-- 1. Add NLP metrics columns to source_document
-- =================================================================

-- Add sentence count column (number of sentences extracted during processing)
ALTER TABLE source_document ADD COLUMN sentence_count INTEGER NOT NULL DEFAULT 0;

-- Add token count column (number of tokens/words processed)
ALTER TABLE source_document ADD COLUMN token_count INTEGER NOT NULL DEFAULT 0;

-- Create indexes for potential filtering/sorting by these metrics
CREATE INDEX IF NOT EXISTS idx_doc_sentence_count ON source_document(sentence_count);
CREATE INDEX IF NOT EXISTS idx_doc_token_count ON source_document(token_count);

-- =================================================================
-- 2. Update schema version
-- =================================================================

UPDATE schema_meta SET value = '3' WHERE key = 'schema_version';

-- =================================================================
-- Migration 003 complete
-- =================================================================
