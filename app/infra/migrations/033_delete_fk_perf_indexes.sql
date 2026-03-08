-- Migration 033: Add indexes for heavy FK cleanup paths on large SQLite DBs.
-- Purpose:
-- - prevent full-table scans during document/project delete and reprocess flows
-- - accelerate ON DELETE SET NULL / maintenance updates that target sentence/doc FKs

CREATE INDEX IF NOT EXISTS idx_lemma_doc_sample_sentence
    ON lemma_doc_stat(sample_sentence_id)
    WHERE sample_sentence_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_lemma_proj_sample_sentence
    ON lemma_project_stat(sample_sentence_id)
    WHERE sample_sentence_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ngram_doc_sample_sentence
    ON ngram_doc_stat(sample_sentence_id)
    WHERE sample_sentence_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ngram_proj_sample_sentence
    ON ngram_project_stat(sample_sentence_id)
    WHERE sample_sentence_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_term_card_pinned_sentence
    ON term_card(pinned_sentence_id)
    WHERE pinned_sentence_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_term_cluster_pinned_example_sent
    ON term_cluster(pinned_example_sent_id)
    WHERE pinned_example_sent_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_run_error_doc
    ON run_error(doc_id)
    WHERE doc_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_user_dictionary_item_origin_doc
    ON user_dictionary_item(origin_doc_id)
    WHERE origin_doc_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_task_queue_doc
    ON task_queue(doc_id)
    WHERE doc_id IS NOT NULL;

UPDATE schema_meta SET value = '33' WHERE key = 'schema_version';
