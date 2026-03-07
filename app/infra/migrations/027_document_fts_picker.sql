-- Migration 027: document FTS5 + composite index for picker performance (PERF-SCALE PATCH-D)
-- Date: 2026-03-07
--
-- Scope:
--   1. idx_doc_corpus_doc_id_desc  — eliminates TEMP B-TREE for picker empty-search ORDER BY.
--      Covers ORDER BY d.doc_id DESC with a leading corpus_id equality filter.
--   2. document_name_fts           — FTS5 content table on source_document.file_name.
--      Replaces LIKE '%query%' scan on 387K rows with sub-millisecond index lookup.
--   3. Sync triggers               — keep FTS index in sync with source_document mutations.
--
-- NOTE: FTS rebuild (INSERT INTO document_name_fts VALUES('rebuild')) is intentionally
--       omitted from this migration. It runs on first startup via _ensure_fts_health()
--       to avoid holding a write lock for the full 387K-row rebuild duration.

-- 1. Composite index: eliminates TEMP B-TREE for empty-search picker ORDER BY doc_id DESC.
CREATE INDEX IF NOT EXISTS idx_doc_corpus_doc_id_desc
    ON source_document(corpus_id, doc_id DESC);

-- 2. FTS5 content table — indexes file_name, backed by source_document.
--    content_rowid=doc_id maps FTS rowid to source_document.doc_id.
--    unicode61 remove_diacritics 1: consistent with existing sentence_fts / term_fts tables.
CREATE VIRTUAL TABLE IF NOT EXISTS document_name_fts USING fts5(
    file_name,
    content=source_document,
    content_rowid=doc_id,
    tokenize='unicode61 remove_diacritics 1'
);

-- 3. Sync triggers: keep FTS index in sync after any mutation on source_document.file_name.

CREATE TRIGGER IF NOT EXISTS trg_doc_name_fts_ai
AFTER INSERT ON source_document BEGIN
    INSERT INTO document_name_fts(rowid, file_name)
        VALUES (new.doc_id, new.file_name);
END;

CREATE TRIGGER IF NOT EXISTS trg_doc_name_fts_au
AFTER UPDATE OF file_name ON source_document BEGIN
    INSERT INTO document_name_fts(document_name_fts, rowid, file_name)
        VALUES ('delete', old.doc_id, old.file_name);
    INSERT INTO document_name_fts(rowid, file_name)
        VALUES (new.doc_id, new.file_name);
END;

CREATE TRIGGER IF NOT EXISTS trg_doc_name_fts_ad
AFTER DELETE ON source_document BEGIN
    INSERT INTO document_name_fts(document_name_fts, rowid, file_name)
        VALUES ('delete', old.doc_id, old.file_name);
END;

UPDATE schema_meta SET value = '27' WHERE key = 'schema_version';
