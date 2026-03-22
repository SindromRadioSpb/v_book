BEGIN;

-- Epic 5B PATCH-06: ngram_n_set column on term_cluster
--
-- ngram_n_set TEXT
--   Canonical JSON representation of the set of ngram sizes (n values)
--   that produced the members of this cluster.
--
--   Format contract:
--     - JSON array of integers, sorted ascending, no duplicates
--     - Compact serialization: no spaces
--     - Examples: "[2]", "[3]", "[2,3]"
--     - NULL for clusters sourced entirely from NP chunks (source_kind='np'),
--       where n-size is not meaningful.
--
--   Distinction from source_kinds:
--     source_kinds = 'ngram' vs 'np' (what kind of extraction)
--     ngram_n_set  = [2] vs [3] vs [2,3] (which n-sizes, only for 'ngram' source)
--
--   Used by:
--     - Replace Layer mode: DELETE WHERE ngram_n_set = '[2]' to remove only bigrams
--     - UI display: "[2]" → "Bigrams", "[3]" → "Trigrams", "[2,3]" → "Bigrams + Trigrams"
--     - Provenance: tells the user exactly which extraction parameters produced this cluster

ALTER TABLE term_cluster ADD COLUMN ngram_n_set TEXT;

-- Index for Replace Layer scoped deletes:
-- DELETE ... WHERE project_id = ? AND ngram_n_set = ?
CREATE INDEX IF NOT EXISTS idx_term_cluster_ngram_n_set
    ON term_cluster(project_id, ngram_n_set);

UPDATE schema_meta
SET value = '46'
WHERE key = 'schema_version';

COMMIT;
