-- Migration 019: Persist last review grade/time for SRS progress
-- Date: 2026-02-19
-- Purpose:
--   1) Add last_grade + last_graded_at to study_progress
--   2) Enable premium summary counters (Added/Again/Hard/Good/Easy)

ALTER TABLE study_progress ADD COLUMN last_grade TEXT;
ALTER TABLE study_progress ADD COLUMN last_graded_at TEXT;

CREATE INDEX IF NOT EXISTS idx_study_progress_last_grade ON study_progress(last_grade);

UPDATE schema_meta SET value = '19' WHERE key = 'schema_version';
