BEGIN;

-- PATCH-08: Epic 4 — staleness tracking for keyness/weirdness
--
-- reference_project_id: snapshot of general_corpus_id at the time of extraction.
--   NULL  = extraction ran before this migration, or no reference corpus was set.
--   non-NULL = ID of reference project used during the last metrics computation.
--
-- Used by Terms view to detect when the user has changed the reference corpus
-- since the last extraction/recalculation, triggering the staleness warning.

ALTER TABLE term_extract_run
    ADD COLUMN reference_project_id INTEGER REFERENCES dict_project(project_id) ON DELETE SET NULL;

UPDATE schema_meta
SET value = '44'
WHERE key = 'schema_version';

COMMIT;
