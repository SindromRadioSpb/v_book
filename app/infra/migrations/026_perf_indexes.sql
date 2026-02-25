-- Migration 026: Performance indexes for hewiki-scale read paths
-- Date: 2026-02-25
-- Purpose:
-- 1) accelerate Dictionary sorting by doc_freq with deterministic tie-break
-- 2) accelerate Document picker file-name ordered paging per corpus/project

CREATE INDEX IF NOT EXISTS idx_lemma_proj_doc_freq
    ON lemma_project_stat(project_id, doc_freq DESC, lemma_id);

CREATE INDEX IF NOT EXISTS idx_doc_corpus_file_name
    ON source_document(corpus_id, file_name, doc_id);

UPDATE schema_meta SET value = '26' WHERE key = 'schema_version';
