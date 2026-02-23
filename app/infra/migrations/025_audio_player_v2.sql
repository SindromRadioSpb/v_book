-- Migration 025: Audio Player v2 — Queue / Playlists / History
-- Date: 2026-02-23
-- Purpose: Persistent, non-destructive queue with playlists and history for
--          premium audio-learning workflow.  Queue items are never removed on play;
--          a cursor advances instead.  History is append-only.

-- ── audio_queue_item ─────────────────────────────────────────────────────────
-- One row per position in the playback queue.  `position` is the sort key.
-- Source reference (kind + source_id + project_id) allows "Go to source".
-- Snapshot columns cache Hebrew/niqqud/translation so the player can display
-- content without joining back to the sentence/term tables on every paint.

CREATE TABLE IF NOT EXISTS audio_queue_item (
    item_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    position            INTEGER NOT NULL DEFAULT 0,
    kind                TEXT    NOT NULL DEFAULT 'sentence',
    source_id           INTEGER,
    project_id          INTEGER,

    -- Snapshot for display (no join needed at play time)
    snapshot_hebrew     TEXT,
    snapshot_niqqud     TEXT,
    snapshot_translation TEXT,
    snapshot_source_label TEXT,

    -- Audio asset link
    audio_asset_id      INTEGER,
    audio_status        TEXT    NOT NULL DEFAULT 'unknown',

    -- Staleness: 1 = source text/pronunciation changed after this item was added
    is_stale            INTEGER NOT NULL DEFAULT 0,

    -- Playback stats
    play_count          INTEGER NOT NULL DEFAULT 0,
    last_played_at      TEXT,

    created_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    FOREIGN KEY (audio_asset_id) REFERENCES audio_asset(asset_id) ON DELETE SET NULL,
    CHECK(kind IN ('sentence', 'lemma', 'term', 'custom_text')),
    CHECK(audio_status IN ('unknown', 'ready', 'missing', 'generating', 'failed')),
    CHECK(is_stale IN (0, 1)),
    CHECK(play_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_aq_item_position
    ON audio_queue_item(position);

CREATE INDEX IF NOT EXISTS idx_aq_item_source
    ON audio_queue_item(kind, source_id, project_id);

CREATE INDEX IF NOT EXISTS idx_aq_item_stale
    ON audio_queue_item(is_stale)
    WHERE is_stale = 1;

-- ── audio_playlist ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audio_playlist (
    playlist_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT    NOT NULL,
    created_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    UNIQUE(name)
);

-- ── audio_playlist_entry ─────────────────────────────────────────────────────
-- Playlist items are independent copies of the snapshot + source ref (not FK
-- to audio_queue_item, so playlists survive queue clears).

CREATE TABLE IF NOT EXISTS audio_playlist_entry (
    entry_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id         INTEGER NOT NULL,
    position            INTEGER NOT NULL DEFAULT 0,
    kind                TEXT    NOT NULL DEFAULT 'sentence',
    source_id           INTEGER,
    project_id          INTEGER,

    snapshot_hebrew     TEXT,
    snapshot_niqqud     TEXT,
    snapshot_translation TEXT,
    snapshot_source_label TEXT,

    audio_asset_id      INTEGER,
    audio_status        TEXT    NOT NULL DEFAULT 'unknown',

    created_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    FOREIGN KEY (playlist_id) REFERENCES audio_playlist(playlist_id) ON DELETE CASCADE,
    FOREIGN KEY (audio_asset_id) REFERENCES audio_asset(asset_id) ON DELETE SET NULL,
    CHECK(kind IN ('sentence', 'lemma', 'term', 'custom_text')),
    CHECK(audio_status IN ('unknown', 'ready', 'missing', 'generating', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_ape_playlist_position
    ON audio_playlist_entry(playlist_id, position);

-- ── audio_history ────────────────────────────────────────────────────────────
-- Append-only listen history.  Never delete rows (used for statistics).

CREATE TABLE IF NOT EXISTS audio_history (
    history_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind                TEXT    NOT NULL DEFAULT 'sentence',
    source_id           INTEGER,
    project_id          INTEGER,
    snapshot_hebrew     TEXT,
    rate_used           REAL    NOT NULL DEFAULT 1.0,
    played_at           TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    CHECK(kind IN ('sentence', 'lemma', 'term', 'custom_text')),
    CHECK(rate_used > 0)
);

CREATE INDEX IF NOT EXISTS idx_ah_played_at
    ON audio_history(played_at DESC);

CREATE INDEX IF NOT EXISTS idx_ah_source
    ON audio_history(kind, source_id, project_id);

UPDATE schema_meta SET value = '25' WHERE key = 'schema_version';
