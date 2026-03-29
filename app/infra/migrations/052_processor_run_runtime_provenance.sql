-- Migration 052: Processor run runtime provenance promotion
-- Date: 2026-03-29
-- Purpose:
--   1) add dedicated schema-backed runtime provenance fields to processor_run
--   2) keep legacy note envelope intact for backward compatibility
--   3) enable SQL/debug/audit paths without reparsing note JSON for new runs

ALTER TABLE processor_run ADD COLUMN configured_engine_id TEXT;
ALTER TABLE processor_run ADD COLUMN effective_engine_id TEXT;
ALTER TABLE processor_run ADD COLUMN fallback_used INTEGER;
ALTER TABLE processor_run ADD COLUMN runtime_reason_code TEXT;
ALTER TABLE processor_run ADD COLUMN runtime_mode TEXT;
ALTER TABLE processor_run ADD COLUMN runtime_probe_summary_json TEXT;

UPDATE schema_meta SET value = '52' WHERE key = 'schema_version';
