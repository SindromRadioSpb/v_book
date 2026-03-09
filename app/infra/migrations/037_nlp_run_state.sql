-- Migration 037: NLP processor run state foundation
-- Date: 2026-03-09
-- Purpose:
--   1) extend processor_run for staged/resumable NLP orchestration
--   2) preserve legacy processor_run rows
--   3) prepare crash recovery for richer run-state semantics

PRAGMA foreign_keys=OFF;

CREATE TABLE processor_run_new (
  run_id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES dict_project(project_id) ON DELETE CASCADE,
  started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  finished_at TEXT,
  engine TEXT NOT NULL,
  engine_version TEXT,
  docs_total INTEGER NOT NULL DEFAULT 0 CHECK(docs_total >= 0),
  docs_processed INTEGER NOT NULL DEFAULT 0 CHECK(docs_processed >= 0),
  docs_failed INTEGER NOT NULL DEFAULT 0 CHECK(docs_failed >= 0),
  chunks_total INTEGER NOT NULL DEFAULT 0 CHECK(chunks_total >= 0),
  chunks_completed INTEGER NOT NULL DEFAULT 0 CHECK(chunks_completed >= 0),
  tokens_total INTEGER NOT NULL DEFAULT 0,
  lemmas_total INTEGER NOT NULL DEFAULT 0,
  ngrams_total INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'running',
  stage TEXT,
  last_doc_id INTEGER,
  params_hash TEXT,
  error_message TEXT,
  note TEXT,
  CHECK (status IN ('running','paused','cancelled','ok','failed'))
);

INSERT INTO processor_run_new (
  run_id,
  project_id,
  started_at,
  finished_at,
  engine,
  engine_version,
  docs_total,
  docs_processed,
  docs_failed,
  chunks_total,
  chunks_completed,
  tokens_total,
  lemmas_total,
  ngrams_total,
  status,
  stage,
  last_doc_id,
  params_hash,
  error_message,
  note
)
SELECT
  run_id,
  project_id,
  started_at,
  finished_at,
  engine,
  engine_version,
  CASE
    WHEN docs_processed > 0 THEN docs_processed
    ELSE 1
  END AS docs_total,
  docs_processed,
  CASE
    WHEN status = 'failed' THEN 1
    ELSE 0
  END AS docs_failed,
  1 AS chunks_total,
  CASE
    WHEN status = 'ok' THEN 1
    ELSE 0
  END AS chunks_completed,
  tokens_total,
  lemmas_total,
  ngrams_total,
  status,
  CASE
    WHEN status = 'ok' THEN 'completed'
    WHEN status = 'failed' THEN 'failed'
    ELSE 'processing'
  END AS stage,
  NULL AS last_doc_id,
  NULL AS params_hash,
  NULL AS error_message,
  note
FROM processor_run;

DROP TABLE processor_run;
ALTER TABLE processor_run_new RENAME TO processor_run;

CREATE INDEX IF NOT EXISTS idx_processor_run_project_status_run
  ON processor_run(project_id, status, run_id);

PRAGMA foreign_keys=ON;

UPDATE schema_meta SET value = '37' WHERE key = 'schema_version';
