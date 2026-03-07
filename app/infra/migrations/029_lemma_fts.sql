-- Migration 029: lemma_fts FTS5 content table (PERF-SCALE PATCH-E)
-- Date: 2026-03-07
--
-- Replaces LIKE '%search%' full-scans on the lemma table with sub-millisecond
-- FTS5 prefix lookups.  On a hewiki-scale project (~500K lemmas) this drops
-- dictionary search latency from ~300ms to <5ms.
--
-- Design:
--   content=lemma, content_rowid=lemma_id  — lightweight external-content table
--   (FTS stores only the inverted index, not the original text).
--   unicode61 remove_diacritics 1          — consistent with sentence_fts / term_fts.
--
-- Rebuild note: intentionally omitted from this migration; runs on first startup
-- via ensure_lemma_fts_health() (avoid long write-lock during app start on large DBs).

CREATE VIRTUAL TABLE IF NOT EXISTS lemma_fts USING fts5(
    lemma_text,
    content=lemma,
    content_rowid=lemma_id,
    tokenize='unicode61 remove_diacritics 1'
);

-- Sync triggers: keep FTS index consistent after any mutation on lemma.lemma_text.

CREATE TRIGGER IF NOT EXISTS trg_lemma_fts_ai
AFTER INSERT ON lemma BEGIN
    INSERT INTO lemma_fts(rowid, lemma_text)
        VALUES (new.lemma_id, new.lemma_text);
END;

CREATE TRIGGER IF NOT EXISTS trg_lemma_fts_au
AFTER UPDATE OF lemma_text ON lemma BEGIN
    INSERT INTO lemma_fts(lemma_fts, rowid, lemma_text)
        VALUES ('delete', old.lemma_id, old.lemma_text);
    INSERT INTO lemma_fts(rowid, lemma_text)
        VALUES (new.lemma_id, new.lemma_text);
END;

CREATE TRIGGER IF NOT EXISTS trg_lemma_fts_ad
AFTER DELETE ON lemma BEGIN
    INSERT INTO lemma_fts(lemma_fts, rowid, lemma_text)
        VALUES ('delete', old.lemma_id, old.lemma_text);
END;

UPDATE schema_meta SET value = '29' WHERE key = 'schema_version';
