-- Migration 030: sort-covering indexes for TM + Documents + Sentences tabs
-- Date: 2026-03-07
--
-- Fixes measurable latency regressions on large projects (hewiki scale):
--
--   tm_entry ORDER BY updated_at DESC  (default TM sort)
--     BEFORE: 426 ms  (TEMP B-TREE on 2 M rows)
--     AFTER:  < 5 ms  (covering index scan)
--
--   source_document ORDER BY imported_at DESC  (default Documents sort)
--     BEFORE: 137 ms  (TEMP B-TREE on 387 K rows)
--     AFTER:  < 5 ms  (covering index scan)
--
--   SUM(sentence_count) from source_document (Sentences fast-count path)
--     BEFORE: 133 ms  (heap-fetch on each of 387 K rows)
--     AFTER:  ~10 ms  (covering index scan - no heap fetch)
--
-- All indexes use CREATE INDEX IF NOT EXISTS so they are safe to re-run
-- and are automatically applied via the schema_version migration gate.

-- ── TM tab ───────────────────────────────────────────────────────────────────
-- Default sort: updated_at DESC.  Also covers kind-filtered searches.
CREATE INDEX IF NOT EXISTS idx_tm_entry_proj_updated_at
    ON tm_entry(project_id, updated_at DESC);

-- ── Documents tab ─────────────────────────────────────────────────────────────
-- Default sort: imported_at DESC
CREATE INDEX IF NOT EXISTS idx_doc_corpus_imported_at
    ON source_document(corpus_id, imported_at DESC);

-- sentence_count and token_count sort columns (non-default but common)
CREATE INDEX IF NOT EXISTS idx_doc_corpus_sentence_count_cov
    ON source_document(corpus_id, sentence_count DESC);

CREATE INDEX IF NOT EXISTS idx_doc_corpus_token_count_cov
    ON source_document(corpus_id, token_count DESC);

-- ── Sentences tab – fast COUNT path ─────────────────────────────────────────
-- Enables covering-index scan for SUM(sentence_count) WHERE corpus_id=?
-- so the Sentences pagination total avoids the slow 13 M-row JOIN COUNT.
-- (sentence_count is non-negative; no partial-index restriction needed)
CREATE INDEX IF NOT EXISTS idx_doc_corpus_sentence_count_sum
    ON source_document(corpus_id, sentence_count);

UPDATE schema_meta SET value = '30' WHERE key = 'schema_version';
