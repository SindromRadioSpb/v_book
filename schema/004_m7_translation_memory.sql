-- M7: Translation Memory, Offline Dictionary Import, MT Cache
-- Schema version: 4 → 5

-- ============================================================================
-- 1. Translation Memory
-- ============================================================================

-- Main TM entries with versioning and provenance
CREATE TABLE IF NOT EXISTS tm_entry (
    tm_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NULL,  -- NULL = global TM
    kind TEXT NOT NULL CHECK(kind IN ('lemma', 'ngram', 'term_cluster', 'surface')),
    src_lang TEXT NOT NULL,
    tgt_lang TEXT NOT NULL,
    src_text TEXT NOT NULL,  -- Original text
    src_norm TEXT NOT NULL,  -- Normalized key for exact match
    translation TEXT NOT NULL,
    translation_norm TEXT NULL,  -- Normalized translation for search
    pos TEXT NULL,
    domain TEXT NULL,
    notes TEXT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft', 'approved', 'rejected', 'deprecated')),
    confidence REAL NULL CHECK(confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    origin TEXT NOT NULL CHECK(origin IN ('user_edit', 'import', 'mt_accept', 'mt_auto', 'merge')),
    source_ref TEXT NULL,  -- Dict name, file, or MT provider
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    approved_at TEXT NULL,
    approved_by TEXT NULL,

    FOREIGN KEY (project_id) REFERENCES dict_project(project_id) ON DELETE CASCADE,

    -- Guarantee: one override per (scope, kind, src, langs)
    UNIQUE (project_id, kind, src_lang, tgt_lang, src_norm)
);

CREATE INDEX IF NOT EXISTS idx_tm_entry_lookup
    ON tm_entry(project_id, status, kind);

CREATE INDEX IF NOT EXISTS idx_tm_entry_src_norm
    ON tm_entry(src_norm);

CREATE INDEX IF NOT EXISTS idx_tm_entry_translation_norm
    ON tm_entry(translation_norm);

-- TM history for audit trail and revert
CREATE TABLE IF NOT EXISTS tm_entry_history (
    hist_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tm_id INTEGER NOT NULL,
    version INTEGER NOT NULL,
    translation TEXT NOT NULL,
    notes TEXT NULL,
    status TEXT NOT NULL,
    origin TEXT NOT NULL,
    changed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    change_kind TEXT NOT NULL CHECK(change_kind IN ('edit', 'import', 'merge', 'revert', 'approve', 'reject', 'deprecate')),

    FOREIGN KEY (tm_id) REFERENCES tm_entry(tm_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_tm_history_tm_version
    ON tm_entry_history(tm_id, version DESC);

-- TM aliases for variant matching (e.g., "בית ספר" alias for "בית הספר")
CREATE TABLE IF NOT EXISTS tm_alias (
    alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tm_id INTEGER NOT NULL,
    alias_text TEXT NOT NULL,
    alias_norm TEXT NOT NULL,

    FOREIGN KEY (tm_id) REFERENCES tm_entry(tm_id) ON DELETE CASCADE,

    UNIQUE (tm_id, alias_norm)
);

CREATE INDEX IF NOT EXISTS idx_tm_alias_norm
    ON tm_alias(alias_norm);

-- ============================================================================
-- 2. Offline Dictionary Sources
-- ============================================================================

-- Dictionary source metadata
CREATE TABLE IF NOT EXISTS dict_source (
    dict_source_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NULL,  -- NULL = global dict
    name TEXT NOT NULL,
    format TEXT NOT NULL CHECK(format IN ('csv', 'xlsx', 'json')),
    file_path TEXT NULL,
    sha256 TEXT NOT NULL,  -- Dedup: don't re-import same file
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    row_count INTEGER NOT NULL DEFAULT 0,
    notes TEXT NULL,

    FOREIGN KEY (project_id) REFERENCES dict_project(project_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_dict_source_sha256
    ON dict_source(sha256);

-- Dictionary entries (imported from files)
CREATE TABLE IF NOT EXISTS dict_entry (
    dict_entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
    dict_source_id INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('lemma', 'ngram', 'term_cluster', 'surface')),
    src_lang TEXT NOT NULL,
    tgt_lang TEXT NOT NULL,
    src_text TEXT NOT NULL,
    src_norm TEXT NOT NULL,
    translation TEXT NOT NULL,
    pos TEXT NULL,
    domain TEXT NULL,
    status TEXT NOT NULL DEFAULT 'approved' CHECK(status IN ('approved', 'draft', 'deprecated')),
    priority INTEGER NOT NULL DEFAULT 0,  -- Higher priority wins in resolve
    notes TEXT NULL,

    FOREIGN KEY (dict_source_id) REFERENCES dict_source(dict_source_id) ON DELETE CASCADE,

    -- Prevent duplicates within same source
    UNIQUE (dict_source_id, kind, src_lang, tgt_lang, src_norm, translation)
);

CREATE INDEX IF NOT EXISTS idx_dict_entry_lookup
    ON dict_entry(src_norm, kind, status);

CREATE INDEX IF NOT EXISTS idx_dict_entry_priority
    ON dict_entry(priority DESC);

-- ============================================================================
-- 3. MT Cache (Premium)
-- ============================================================================

-- Machine Translation cache for API results
CREATE TABLE IF NOT EXISTS mt_cache (
    cache_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NULL,
    provider TEXT NOT NULL,
    src_lang TEXT NOT NULL,
    tgt_lang TEXT NOT NULL,
    request_key TEXT NOT NULL,  -- Hash: src_norm + glossary_hash + options_hash
    src_text TEXT NOT NULL,
    src_norm TEXT NOT NULL,
    glossary_hash TEXT NULL,
    translation TEXT NOT NULL,
    confidence REAL NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    expires_at TEXT NULL,

    UNIQUE (provider, src_lang, tgt_lang, request_key)
);

CREATE INDEX IF NOT EXISTS idx_mt_cache_norm
    ON mt_cache(src_norm);

CREATE INDEX IF NOT EXISTS idx_mt_cache_expiry
    ON mt_cache(expires_at);

-- ============================================================================
-- 4. Schema Version Update
-- ============================================================================

UPDATE schema_meta SET value = '5' WHERE key = 'schema_version';

-- Verify
SELECT key, value FROM schema_meta WHERE key = 'schema_version';
