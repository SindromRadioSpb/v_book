-- Migration 035: Audio asset content-addressed cache hardening
-- Date: 2026-03-08
-- Purpose:
--   1) Add pronunciation-aware speech_hash for current spoken payload identity
--   2) Add provider/request-specific input_hash for exact cache reuse
--   3) Keep legacy weak key for bounded backward compatibility

ALTER TABLE audio_asset ADD COLUMN speech_hash TEXT;
ALTER TABLE audio_asset ADD COLUMN input_hash TEXT;

-- Backfill legacy rows with stable fallback hashes.
UPDATE audio_asset
SET speech_hash = lower(hex(randomblob(16)))
WHERE speech_hash IS NULL OR trim(speech_hash) = '';

UPDATE audio_asset
SET input_hash = lower(hex(randomblob(16)))
WHERE input_hash IS NULL OR trim(input_hash) = '';

CREATE INDEX IF NOT EXISTS idx_audio_asset_lang_speech_hash
    ON audio_asset(lang, speech_hash);

CREATE INDEX IF NOT EXISTS idx_audio_asset_lang_input_hash
    ON audio_asset(lang, input_hash);

UPDATE schema_meta SET value = '35' WHERE key = 'schema_version';
