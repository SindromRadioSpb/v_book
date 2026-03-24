BEGIN;

-- Migration 050: Second pass noise_source backfill.
--
-- Migration 049 was committed with incorrect schema_version tracking (manual
-- executescript did not checkpoint WAL before close). This migration is
-- functionally identical to 049 and will be applied automatically by the
-- migration runner (50 > 49).

-- Lemma: any remaining gaps
UPDATE lemma
SET noise_source = 'auto'
WHERE is_noise IS NOT NULL
  AND noise_source IS NULL;

-- TermCluster: any remaining gaps
UPDATE term_cluster
SET noise_source = 'auto'
WHERE is_noise IS NOT NULL
  AND noise_source IS NULL;

-- TMEntry step 1: inherit from linked lemma
UPDATE tm_entry
SET noise_source = (
    SELECT l.noise_source
    FROM lemma l
    WHERE l.lemma_id = tm_entry.lemma_id
      AND l.noise_source IS NOT NULL
)
WHERE lemma_id IS NOT NULL
  AND is_noise IS NOT NULL
  AND noise_source IS NULL;

-- TMEntry step 2: inherit from linked cluster
UPDATE tm_entry
SET noise_source = (
    SELECT tc.noise_source
    FROM term_cluster tc
    WHERE tc.cluster_id = tm_entry.cluster_id
      AND tc.noise_source IS NOT NULL
)
WHERE cluster_id IS NOT NULL
  AND is_noise IS NOT NULL
  AND noise_source IS NULL;

-- TMEntry step 3: fallback to 'auto'
UPDATE tm_entry
SET noise_source = 'auto'
WHERE is_noise IS NOT NULL
  AND noise_source IS NULL;

UPDATE schema_meta
SET value = '50'
WHERE key = 'schema_version';

COMMIT;
