-- Migration 014: DB-level triggers for is_noise synchronization
-- Date: 2026-02-13
-- Purpose: Guarantee Dictionary/Terms -> TM Panel sync via SQLite triggers

-- =================================================================
-- Background: Why triggers?
-- =================================================================
-- Previous implementation (migrations 012/013) used application-level sync in workers.py.
-- This was fragile because:
-- 1. Worker code could fail to sync (session issues, column reference bugs)
-- 2. Depends on correct calling order and session lifecycle
-- 3. Refresh button didn't work reliably
--
-- Solution: DB-level triggers guarantee sync happens on EVERY UPDATE to lemma/term_cluster.
-- If lemma.is_noise changes, trigger automatically updates ALL linked tm_entry records.
-- This is atomic, transactional, and cannot be forgotten by application code.

-- =================================================================
-- Trigger 1: lemma.is_noise -> tm_entry.is_noise
-- =================================================================
-- When a lemma's noise status changes, update all linked TM entries
DROP TRIGGER IF EXISTS trg_lemma_noise_to_tm_entry;
CREATE TRIGGER trg_lemma_noise_to_tm_entry
AFTER UPDATE OF is_noise, noise_reason ON lemma
WHEN (NEW.is_noise IS NOT OLD.is_noise) OR (NEW.noise_reason IS NOT OLD.noise_reason)
BEGIN
  UPDATE tm_entry
  SET is_noise = COALESCE(NEW.is_noise, 0),
      noise_reason = NEW.noise_reason
  WHERE tm_entry.lemma_id = NEW.lemma_id;
END;

-- =================================================================
-- Trigger 2: term_cluster.is_noise -> tm_entry.is_noise
-- =================================================================
-- When a term cluster's noise status changes, update all linked TM entries
DROP TRIGGER IF EXISTS trg_cluster_noise_to_tm_entry;
CREATE TRIGGER trg_cluster_noise_to_tm_entry
AFTER UPDATE OF is_noise, noise_reason ON term_cluster
WHEN (NEW.is_noise IS NOT OLD.is_noise) OR (NEW.noise_reason IS NOT OLD.noise_reason)
BEGIN
  UPDATE tm_entry
  SET is_noise = COALESCE(NEW.is_noise, 0),
      noise_reason = NEW.noise_reason
  WHERE tm_entry.cluster_id = NEW.cluster_id;
END;

-- =================================================================
-- Schema version update
-- =================================================================
-- Update to version 14
-- Note: Migrations 012 and 013 forgot to update schema_version,
-- so this also effectively confirms them as applied
UPDATE schema_meta SET value = '14' WHERE key = 'schema_version';
