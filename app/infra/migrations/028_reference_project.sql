-- Migration 028: reference project support (PERF-SCALE PATCH-A)
-- Date: 2026-03-07
--
-- Adds is_reference + ref_db_path to dict_project so that a project can be
-- declared as a read-only reference corpus mounted from a separate DB file.
--
-- Semantics:
--   is_reference = 1  → project's data lives in ref_db_path (read-only mount).
--                       All mutation operations on this project raise
--                       ReferenceProjectReadOnlyError at the service layer.
--   ref_db_path       → Absolute path to the external SQLite DB file that holds
--                       the reference data (e.g. hewiki_gpu_processing.db).
--                       NULL for normal (writable) projects.
--
-- Note: is_reference is intentionally separate from is_general_corpus.
--   is_general_corpus = used as reference corpus for term extraction scoring.
--   is_reference      = physical read-only DB mount and mutation guard.
-- These flags are independent: a project can be a general corpus without being
-- a read-only reference, and vice versa.

ALTER TABLE dict_project ADD COLUMN is_reference INTEGER NOT NULL DEFAULT 0;
ALTER TABLE dict_project ADD COLUMN ref_db_path TEXT;

CREATE INDEX IF NOT EXISTS idx_project_reference
    ON dict_project(is_reference);

UPDATE schema_meta SET value = '28' WHERE key = 'schema_version';
