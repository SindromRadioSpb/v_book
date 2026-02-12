-- Migration 011: Term Extraction Parameters Tracking
-- Add fields to track last term extraction parameters for UX feedback

-- Add columns to dict_project to track last extraction parameters
ALTER TABLE dict_project ADD COLUMN last_extract_np_max_len INTEGER DEFAULT NULL;
ALTER TABLE dict_project ADD COLUMN last_extract_min_freq INTEGER DEFAULT NULL;
ALTER TABLE dict_project ADD COLUMN last_extract_at TEXT DEFAULT NULL;
ALTER TABLE dict_project ADD COLUMN last_extract_include_np INTEGER DEFAULT 0;

-- Update schema version
UPDATE schema_meta SET value = '11' WHERE key = 'schema_version';
