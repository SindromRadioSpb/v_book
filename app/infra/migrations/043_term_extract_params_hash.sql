BEGIN;

-- PATCH-01: Epic 4 — Term Extraction Pro foundation
--
-- params_hash: canonical SHA-256[:16] of extraction parameters.
--   Payload fields (all included, algo_version bumped on algo logic changes):
--     algo_version, enable_ngrams, include_np, min_freq, ngram_ns (sorted), np_max_len
--   NOTE: overwrite is NOT included (execution mode, not extraction result params).
--   Canonical format: json.dumps(sorted_keys=True, separators=(',',':'))
--
-- best_keyness: LLR-based keyness vs reference corpus, stored at extraction time.
--   NULL  = not computed (reference corpus not configured or not available)
--   0.0   = computed and equals zero
--   Used for server-side ORDER BY; fallback to query-time compute if NULL.

ALTER TABLE term_extract_run
    ADD COLUMN params_hash TEXT;

ALTER TABLE term_cluster
    ADD COLUMN best_keyness REAL;

-- Index for server-side sort by keyness in Terms view.
-- NOTE: Partial optimality — Terms view may also filter by is_noise/status.
-- Accepted for Epic 4; revisit if query profiling shows suboptimal plans.
CREATE INDEX IF NOT EXISTS idx_term_cluster_keyness
    ON term_cluster(project_id, best_keyness DESC);

UPDATE schema_meta
SET value = '43'
WHERE key = 'schema_version';

COMMIT;
