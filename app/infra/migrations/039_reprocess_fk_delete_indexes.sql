-- Reprocess hot-path hardening:
-- deleting orphan lemma rows must not scan large child tables without lemma_id indexes.

CREATE INDEX IF NOT EXISTS idx_lemma_doc_lemma
    ON lemma_doc_stat(lemma_id);

CREATE INDEX IF NOT EXISTS idx_lemma_proj_lemma
    ON lemma_project_stat(lemma_id);

CREATE INDEX IF NOT EXISTS idx_term_card_lemma
    ON term_card(lemma_id)
    WHERE lemma_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_translation_memory_lemma_only
    ON translation_memory(lemma_id)
    WHERE lemma_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ngram_component_lemma
    ON ngram_component(lemma_id);

UPDATE schema_meta SET value = '39' WHERE key = 'schema_version';
