BEGIN;

-- Epic 5A PATCH-01: TM entry provenance — source tracking across re-extractions
--
-- promoted_from_cluster_id
--   Plain INTEGER, intentionally NOT a foreign key (no CASCADE / SET NULL).
--   Stores the cluster_id at the moment of promotion. Never overwritten after
--   first assignment. Survives cluster deletion, giving a permanent audit trail.
--   Contrast with cluster_id (live operational link, goes NULL when cluster deleted).
--
-- promoted_at_params_hash
--   SHA-256[:16] of extraction parameters copied from term_extract_run.params_hash
--   at the moment of promotion. Tells the user "this entry was promoted from an
--   extraction run with these exact settings".
--
-- promoted_at_run_id
--   Soft reference to the extraction run. SET NULL on run deletion (runs can be
--   pruned; loss of the run row does not erase the params_hash snapshot).
--
-- source_status is COMPUTED at query time, never stored:
--   cluster_id IS NOT NULL                                       → 'linked'
--   cluster_id IS NULL AND promoted_from_cluster_id IS NOT NULL  → 'source_cluster_missing'
--   cluster_id IS NULL AND promoted_from_cluster_id IS NULL      → 'manual'

ALTER TABLE tm_entry ADD COLUMN promoted_from_cluster_id INTEGER;

ALTER TABLE tm_entry ADD COLUMN promoted_at_params_hash TEXT;

ALTER TABLE tm_entry ADD COLUMN promoted_at_run_id INTEGER
    REFERENCES term_extract_run(run_id) ON DELETE SET NULL;

UPDATE schema_meta
SET value = '45'
WHERE key = 'schema_version';

COMMIT;
