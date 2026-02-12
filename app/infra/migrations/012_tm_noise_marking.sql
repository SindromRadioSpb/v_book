-- Migration 012: Add noise marking fields to tm_entry
-- Date: 2026-02-12
-- Purpose: Enable noise filtering and marking in Translation Management Panel

-- Add is_noise column (0 = not noise, 1 = noise, NULL for backward compatibility)
ALTER TABLE tm_entry ADD COLUMN is_noise INTEGER DEFAULT 0;

-- Add noise_reason column (stores reason code like NOISE_PUNCT_ONLY, NOISE_NUMBER_ONLY, etc.)
ALTER TABLE tm_entry ADD COLUMN noise_reason TEXT;

-- Add norm_text column for normalized comparison (required for noise detection)
ALTER TABLE tm_entry ADD COLUMN norm_text TEXT;

-- Create index for efficient noise filtering
CREATE INDEX IF NOT EXISTS idx_tm_entry_noise ON tm_entry(is_noise) WHERE is_noise IS NOT NULL;

-- Create index for kind-based queries with noise filter
CREATE INDEX IF NOT EXISTS idx_tm_entry_kind_noise ON tm_entry(kind, is_noise);

-- Update schema version
UPDATE schema_meta SET value = '12' WHERE key = 'schema_version';
