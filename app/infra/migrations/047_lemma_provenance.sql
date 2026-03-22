BEGIN;

-- Epic 6A PATCH-01: Lemma provenance — noise lifecycle + orphan snapshot
--
-- lemma.noise_source TEXT
--   "auto"   — set by classifier (_get_or_create_lemmas, initial classification)
--   "manual" — set by user (set_lemma_noise_status or bulk noise override)
--   NULL     — legacy rows created before Epic 6A (treated as "auto" in UI)
--
-- lemma.noise_updated_at TEXT
--   ISO8601 UTC timestamp of the last noise_source write.
--   NULL for legacy rows.
--   Used to detect stale auto-classification ("this was auto-classified 6 months ago").
--
-- tm_entry.orphaned_lemma_id INTEGER
--   Plain INTEGER, intentionally NOT a foreign key (no CASCADE / SET NULL).
--   Stores the lemma_id at the moment the lemma was deleted by orphan cleanup.
--   Written by _cleanup_orphaned_lemmas_for_ids() BEFORE DELETE.
--   Never overwritten after first assignment (idempotent guard: AND orphaned_lemma_id IS NULL).
--   Survives lemma deletion, giving a permanent audit trail.
--
--   Contrast with lemma_id (live operational link, goes NULL via FK SET NULL when lemma deleted).
--
-- source_lifecycle is COMPUTED at query time, never stored (same pattern as TM source_status):
--   lemma_id IS NOT NULL                                       → 'linked'
--   lemma_id IS NULL AND orphaned_lemma_id IS NOT NULL         → 'source_missing'
--   lemma_id IS NULL AND orphaned_lemma_id IS NULL
--     AND origin IN ('user_edit','manual')                     → 'manual'
--   otherwise                                                  → 'auto_only'

ALTER TABLE lemma ADD COLUMN noise_source TEXT;

ALTER TABLE lemma ADD COLUMN noise_updated_at TEXT;

ALTER TABLE tm_entry ADD COLUMN orphaned_lemma_id INTEGER;

-- Backfill: all existing classified lemmas were set by the auto classifier.
-- Rows with is_noise IS NULL are not yet classified — leave noise_source NULL.
UPDATE lemma
SET noise_source = 'auto'
WHERE is_noise IS NOT NULL
  AND noise_source IS NULL;

UPDATE schema_meta
SET value = '47'
WHERE key = 'schema_version';

COMMIT;
