-- Migration 016: User Dictionaries + Audio Asset Stub (P0)
-- Date: 2026-02-17
-- Purpose:
--   1) Add user_dictionary / user_dictionary_item for study lists (no translation storage)
--   2) Add audio_asset table for future TTS pipeline (status-only in P0)

-- ---------------------------------------------------------------------------
-- User dictionaries
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_dictionary (
    dictionary_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL UNIQUE,
    description   TEXT,
    is_pinned     INTEGER NOT NULL DEFAULT 0 CHECK(is_pinned IN (0, 1)),
    sort_order    INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS user_dictionary_item (
    item_id               INTEGER PRIMARY KEY AUTOINCREMENT,
    dictionary_id         INTEGER NOT NULL REFERENCES user_dictionary(dictionary_id) ON DELETE CASCADE,
    kind                  TEXT NOT NULL CHECK(kind IN ('lemma', 'ngram', 'term_cluster', 'surface')),
    src_lang              TEXT NOT NULL,
    tgt_lang              TEXT NOT NULL,
    src_text              TEXT NOT NULL,
    src_norm              TEXT NOT NULL,
    canonical_hash        TEXT NOT NULL,
    tags_json             TEXT NOT NULL DEFAULT '[]',
    notes                 TEXT,
    is_noise              INTEGER NOT NULL DEFAULT 0 CHECK(is_noise IN (0, 1)),
    noise_reason          TEXT,
    study_state           TEXT NOT NULL DEFAULT 'new' CHECK(study_state IN ('new', 'learning', 'mastered', 'suspended')),
    last_seen_at          TEXT,
    seen_count            INTEGER NOT NULL DEFAULT 0,
    origin_project_id     INTEGER REFERENCES dict_project(project_id) ON DELETE SET NULL,
    origin_entity_type    TEXT,
    origin_entity_id      TEXT,
    origin_tm_entry_id    INTEGER REFERENCES tm_entry(tm_id) ON DELETE SET NULL,
    origin_doc_id         INTEGER REFERENCES source_document(doc_id) ON DELETE SET NULL,
    origin_source_ref     TEXT,
    created_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    UNIQUE(dictionary_id, canonical_hash)
);

CREATE INDEX IF NOT EXISTS idx_user_dict_item_dict_kind ON user_dictionary_item(dictionary_id, kind);
CREATE INDEX IF NOT EXISTS idx_user_dict_item_dict_norm ON user_dictionary_item(dictionary_id, src_norm);
CREATE INDEX IF NOT EXISTS idx_user_dict_item_dict_noise ON user_dictionary_item(dictionary_id, is_noise);
CREATE INDEX IF NOT EXISTS idx_user_dict_item_dict_state ON user_dictionary_item(dictionary_id, study_state);
CREATE INDEX IF NOT EXISTS idx_user_dict_item_dict_hash ON user_dictionary_item(dictionary_id, canonical_hash);

-- ---------------------------------------------------------------------------
-- Audio asset (stub architecture)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audio_asset (
    asset_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    lang          TEXT NOT NULL,
    norm_text     TEXT NOT NULL,
    voice_id      TEXT NOT NULL DEFAULT 'default',
    speed         REAL NOT NULL DEFAULT 1.0,
    provider      TEXT NOT NULL DEFAULT 'none',
    asset_status  TEXT NOT NULL DEFAULT 'missing' CHECK(asset_status IN ('missing', 'ready', 'failed')),
    audio_rel_path TEXT,
    duration_ms   INTEGER,
    sha256        TEXT,
    error_text    TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    UNIQUE(lang, norm_text, voice_id, speed, provider),
    CHECK(
      audio_rel_path IS NULL OR (
        audio_rel_path NOT LIKE '/%' AND
        audio_rel_path NOT LIKE '\\%' AND
        audio_rel_path NOT LIKE '%..%' AND
        audio_rel_path NOT GLOB '[A-Za-z]:*'
      )
    )
);

CREATE INDEX IF NOT EXISTS idx_audio_asset_status ON audio_asset(asset_status);
CREATE INDEX IF NOT EXISTS idx_audio_asset_lookup ON audio_asset(lang, norm_text, voice_id, speed, provider);

-- ---------------------------------------------------------------------------
-- Schema version
-- ---------------------------------------------------------------------------
UPDATE schema_meta SET value = '16' WHERE key = 'schema_version';
