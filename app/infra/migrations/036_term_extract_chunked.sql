-- Migration 036: Chunked term extraction staging + resumable runs
-- Date: 2026-03-09
-- Purpose:
--   1) Persist bounded term-extraction progress by document batches
--   2) Stage aggregate counters before final term-table writes
--   3) Allow safe resume/retry after cancellation or failure

CREATE TABLE IF NOT EXISTS term_extract_run (
    run_id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES dict_project(project_id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'running',
    stage TEXT,
    enable_ngrams INTEGER NOT NULL DEFAULT 1,
    include_np INTEGER NOT NULL DEFAULT 0,
    overwrite INTEGER NOT NULL DEFAULT 1,
    min_freq INTEGER NOT NULL DEFAULT 2,
    ngram_ns_json TEXT NOT NULL DEFAULT '[2,3]',
    np_max_len INTEGER NOT NULL DEFAULT 5,
    engine TEXT,
    engine_version TEXT,
    docs_total INTEGER NOT NULL DEFAULT 0,
    docs_processed INTEGER NOT NULL DEFAULT 0,
    chunks_total INTEGER NOT NULL DEFAULT 0,
    chunks_completed INTEGER NOT NULL DEFAULT 0,
    last_doc_id INTEGER,
    error_message TEXT,
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    finished_at TEXT,
    CHECK (status IN ('running','staged','finalizing','ok','failed','cancelled')),
    CHECK (enable_ngrams IN (0, 1)),
    CHECK (include_np IN (0, 1)),
    CHECK (overwrite IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_term_extract_run_project_status
    ON term_extract_run(project_id, status, run_id);

CREATE TABLE IF NOT EXISTS term_extract_accumulator (
    run_id INTEGER NOT NULL REFERENCES term_extract_run(run_id) ON DELETE CASCADE,
    source_kind TEXT NOT NULL,
    n INTEGER NOT NULL,
    surface_text TEXT NOT NULL,
    lemma_phrase TEXT,
    pos_pattern TEXT,
    freq_abs INTEGER NOT NULL DEFAULT 0,
    doc_freq INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (run_id, source_kind, n, surface_text),
    CHECK (source_kind IN ('ngram', 'np')),
    CHECK (n IN (2, 3, 4, 5)),
    CHECK (freq_abs >= 0),
    CHECK (doc_freq >= 0)
);

CREATE INDEX IF NOT EXISTS idx_term_extract_acc_run_kind_freq
    ON term_extract_accumulator(run_id, source_kind, freq_abs DESC, n, surface_text);

UPDATE schema_meta SET value = '36' WHERE key = 'schema_version';
