BEGIN;

-- Noise provenance unification: add noise_source to term_cluster and tm_entry.
--
-- term_cluster.noise_source TEXT
--   "auto"   — set by NLP classifier at extraction time
--   "manual" — set by user (UI toggle or bulk action)
--   NULL     — legacy rows (treat as "auto" in UI)
--
-- tm_entry.noise_source TEXT
--   Same semantics. Propagated from source entity via DB triggers.
--   Can be overridden to "manual" when user toggles noise directly in TM panel.

ALTER TABLE term_cluster ADD COLUMN noise_source TEXT;
ALTER TABLE tm_entry ADD COLUMN noise_source TEXT;

-- Backfill term_cluster: all existing classified rows are auto-classified
UPDATE term_cluster
SET noise_source = 'auto'
WHERE is_noise IS NOT NULL
  AND noise_source IS NULL;

-- Backfill tm_entry: propagate from linked lemma first (most authoritative)
UPDATE tm_entry
SET noise_source = (
    SELECT l.noise_source FROM lemma l WHERE l.lemma_id = tm_entry.lemma_id
)
WHERE lemma_id IS NOT NULL
  AND is_noise IS NOT NULL
  AND noise_source IS NULL;

-- Backfill tm_entry: propagate from linked cluster (after cluster backfill above)
UPDATE tm_entry
SET noise_source = (
    SELECT tc.noise_source
    FROM term_cluster tc
    WHERE tc.cluster_id = tm_entry.cluster_id
)
WHERE cluster_id IS NOT NULL
  AND is_noise IS NOT NULL
  AND noise_source IS NULL;

-- Backfill remaining tm_entry rows (no linked entity)
UPDATE tm_entry
SET noise_source = 'auto'
WHERE is_noise IS NOT NULL
  AND noise_source IS NULL;

-- Recreate noise sync triggers to propagate noise_source
DROP TRIGGER IF EXISTS trg_lemma_noise_to_tm_entry;
DROP TRIGGER IF EXISTS trg_cluster_noise_to_tm_entry;

CREATE TRIGGER trg_lemma_noise_to_tm_entry
AFTER UPDATE OF is_noise, noise_reason, noise_source ON lemma
WHEN (NEW.is_noise IS NOT OLD.is_noise)
  OR (NEW.noise_reason IS NOT OLD.noise_reason)
  OR (NEW.noise_source IS NOT OLD.noise_source)
BEGIN
  UPDATE tm_entry
  SET is_noise     = COALESCE(NEW.is_noise, 0),
      noise_reason = NEW.noise_reason,
      noise_source = NEW.noise_source
  WHERE tm_entry.lemma_id = NEW.lemma_id;
END;

CREATE TRIGGER trg_cluster_noise_to_tm_entry
AFTER UPDATE OF is_noise, noise_reason, noise_source ON term_cluster
WHEN (NEW.is_noise IS NOT OLD.is_noise)
  OR (NEW.noise_reason IS NOT OLD.noise_reason)
  OR (NEW.noise_source IS NOT OLD.noise_source)
BEGIN
  UPDATE tm_entry
  SET is_noise     = COALESCE(NEW.is_noise, 0),
      noise_reason = NEW.noise_reason,
      noise_source = NEW.noise_source
  WHERE tm_entry.cluster_id = NEW.cluster_id;
END;

UPDATE schema_meta
SET value = '48'
WHERE key = 'schema_version';

COMMIT;
