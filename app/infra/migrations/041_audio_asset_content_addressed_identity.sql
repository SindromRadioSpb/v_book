-- Migration 041: audio_asset content-addressed row identity
-- Date: 2026-03-11
-- Purpose:
--   1) remove legacy weak row uniqueness on (lang, norm_text, voice_id, speed, provider)
--   2) promote (lang, input_hash) to the canonical cache identity for non-legacy rows
--   3) preserve existing asset_id references and keep bounded legacy fallback rows readable

PRAGMA foreign_keys=OFF;

CREATE TABLE audio_asset_new (
    asset_id INTEGER PRIMARY KEY AUTOINCREMENT,
    lang TEXT NOT NULL,
    norm_text TEXT NOT NULL,
    voice_id TEXT NOT NULL DEFAULT 'default',
    speed REAL NOT NULL DEFAULT 1.0,
    provider TEXT NOT NULL DEFAULT 'none',
    speech_hash TEXT,
    input_hash TEXT,
    asset_status TEXT NOT NULL DEFAULT 'missing'
        CHECK(asset_status IN ('missing', 'ready', 'failed')),
    audio_rel_path TEXT,
    duration_ms INTEGER,
    sha256 TEXT,
    error_text TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK(
      audio_rel_path IS NULL OR (
        audio_rel_path NOT LIKE '/%' AND
        audio_rel_path NOT LIKE '\\%' AND
        audio_rel_path NOT LIKE '%..%' AND
        audio_rel_path NOT GLOB '[A-Za-z]:*'
      )
    )
);

-- Preserve the latest row when older DBs contain duplicate (lang, input_hash).
INSERT OR REPLACE INTO audio_asset_new (
    asset_id,
    lang,
    norm_text,
    voice_id,
    speed,
    provider,
    speech_hash,
    input_hash,
    asset_status,
    audio_rel_path,
    duration_ms,
    sha256,
    error_text,
    created_at,
    updated_at
)
SELECT
    asset_id,
    lang,
    norm_text,
    voice_id,
    speed,
    provider,
    speech_hash,
    input_hash,
    asset_status,
    audio_rel_path,
    duration_ms,
    sha256,
    error_text,
    created_at,
    updated_at
FROM audio_asset
WHERE input_hash IS NOT NULL AND trim(input_hash) <> ''
ORDER BY updated_at ASC, asset_id ASC;

INSERT INTO audio_asset_new (
    asset_id,
    lang,
    norm_text,
    voice_id,
    speed,
    provider,
    speech_hash,
    input_hash,
    asset_status,
    audio_rel_path,
    duration_ms,
    sha256,
    error_text,
    created_at,
    updated_at
)
SELECT
    asset_id,
    lang,
    norm_text,
    voice_id,
    speed,
    provider,
    speech_hash,
    input_hash,
    asset_status,
    audio_rel_path,
    duration_ms,
    sha256,
    error_text,
    created_at,
    updated_at
FROM audio_asset
WHERE input_hash IS NULL OR trim(input_hash) = '';

DROP TABLE audio_asset;
ALTER TABLE audio_asset_new RENAME TO audio_asset;

CREATE INDEX IF NOT EXISTS idx_audio_asset_status
    ON audio_asset(asset_status);

CREATE INDEX IF NOT EXISTS idx_audio_asset_lookup
    ON audio_asset(lang, norm_text, voice_id, speed, provider, updated_at, asset_id);

CREATE INDEX IF NOT EXISTS idx_audio_asset_lang_speech_hash
    ON audio_asset(lang, speech_hash, asset_status, updated_at, asset_id);

CREATE INDEX IF NOT EXISTS idx_audio_asset_lang_input_hash
    ON audio_asset(lang, input_hash);

CREATE UNIQUE INDEX IF NOT EXISTS uq_audio_asset_lang_input_hash
    ON audio_asset(lang, input_hash)
    WHERE input_hash IS NOT NULL AND trim(input_hash) <> '';

PRAGMA foreign_keys=ON;

UPDATE schema_meta SET value = '41' WHERE key = 'schema_version';
