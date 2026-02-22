-- Migration 024: sentence_pronunciation table
-- Date: 2026-02-22
-- Purpose: Dedicated sentence-level niqqud layer, keyed by sentence_id (PK) + src_hash (idempotency).
--          Separate from lexical pronunciation_entry (which covers Terms/Lemmas/UD).

CREATE TABLE IF NOT EXISTS sentence_pronunciation (
    sentence_id       INTEGER PRIMARY KEY,
    lang              TEXT    NOT NULL DEFAULT 'he',
    src_hash          TEXT    NOT NULL,
    src_preprocessed  TEXT,
    niqqud_text       TEXT,
    source            TEXT    NOT NULL DEFAULT 'auto_phonikud',
    is_override       INTEGER NOT NULL DEFAULT 0,
    confidence        REAL,
    qc_status         TEXT    NOT NULL DEFAULT 'pending',
    qc_reason         TEXT,
    niqqud_coverage   REAL,
    phonikud_version  TEXT,
    sanitizer_version TEXT    NOT NULL DEFAULT '1',
    error_kind        TEXT,
    error_details     TEXT,
    review_status     TEXT    NOT NULL DEFAULT 'auto',
    created_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    FOREIGN KEY (sentence_id) REFERENCES document_sentence(sentence_id) ON DELETE CASCADE,
    CHECK(source IN ('auto_phonikud', 'manual', 'import_csv')),
    CHECK(is_override IN (0, 1)),
    CHECK(qc_status IN ('ok', 'auto_fixed', 'partial', 'rejected', 'failed', 'pending')),
    CHECK(review_status IN ('auto', 'pending_review', 'approved', 'rejected_by_user')),
    CHECK(confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    CHECK(niqqud_coverage IS NULL OR (niqqud_coverage >= 0 AND niqqud_coverage <= 1))
);

CREATE INDEX IF NOT EXISTS idx_sp_lang_hash
    ON sentence_pronunciation(lang, src_hash);

CREATE INDEX IF NOT EXISTS idx_sp_is_override
    ON sentence_pronunciation(is_override);

CREATE INDEX IF NOT EXISTS idx_sp_qc_status
    ON sentence_pronunciation(qc_status);

CREATE INDEX IF NOT EXISTS idx_sp_review_status
    ON sentence_pronunciation(review_status);

CREATE INDEX IF NOT EXISTS idx_sp_source
    ON sentence_pronunciation(source);

UPDATE schema_meta SET value = '24' WHERE key = 'schema_version';
