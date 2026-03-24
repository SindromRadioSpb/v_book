BEGIN;

-- Migration 049: Idempotent backfill fixup for noise_source across all three tables.
--
-- Why needed: migration 048 adds noise_source columns and runs backfill UPDATEs.
-- If the columns already existed from a partial/dev run, db.py detects
-- "duplicate column name" and forces schema_version=48 WITHOUT running the UPDATE
-- statements. This leaves tm_entry, term_cluster and lemma rows with
-- noise_source IS NULL even though is_noise IS NOT NULL.
--
-- This migration re-runs the backfill idempotently (WHERE noise_source IS NULL).
-- Safe to run even if 048 completed correctly — all WHERE clauses are no-ops then.

-- Lemma: any remaining gaps (migration 047 should have covered these)
UPDATE lemma
SET noise_source = 'auto'
WHERE is_noise IS NOT NULL
  AND noise_source IS NULL;

-- TermCluster: any remaining gaps from migration 048
UPDATE term_cluster
SET noise_source = 'auto'
WHERE is_noise IS NOT NULL
  AND noise_source IS NULL;

-- TMEntry step 1: inherit from linked lemma (if lemma has noise_source set)
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

-- TMEntry step 2: inherit from linked cluster (if cluster has noise_source set)
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

-- TMEntry step 3: fallback to 'auto' for any remaining classified rows
-- (covers: no lemma link, no cluster link, or linked entity had NULL noise_source)
UPDATE tm_entry
SET noise_source = 'auto'
WHERE is_noise IS NOT NULL
  AND noise_source IS NULL;

UPDATE schema_meta
SET value = '49'
WHERE key = 'schema_version';

COMMIT;
