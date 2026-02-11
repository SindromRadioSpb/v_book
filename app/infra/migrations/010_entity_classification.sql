-- Migration 010: Entity Classification
-- Add classification columns to lemma and term_cluster tables
-- Date: 2026-02-11
-- Task 11: Entity Classification & Noise Filtering (PATCH-03)

-- Add classification columns to lemma table
ALTER TABLE lemma ADD COLUMN entity_class TEXT;
ALTER TABLE lemma ADD COLUMN is_noise INTEGER DEFAULT 0;
ALTER TABLE lemma ADD COLUMN noise_reason TEXT;
ALTER TABLE lemma ADD COLUMN norm_text TEXT;

-- Add classification columns to term_cluster table
ALTER TABLE term_cluster ADD COLUMN entity_class TEXT;
ALTER TABLE term_cluster ADD COLUMN is_noise INTEGER DEFAULT 0;
ALTER TABLE term_cluster ADD COLUMN noise_reason TEXT;
ALTER TABLE term_cluster ADD COLUMN norm_text TEXT;

-- Create indexes for efficient filtering
CREATE INDEX idx_lemma_noise ON lemma(project_id, is_noise);
CREATE INDEX idx_lemma_entity_class ON lemma(project_id, entity_class);
CREATE INDEX idx_cluster_noise ON term_cluster(project_id, is_noise);
CREATE INDEX idx_cluster_entity_class ON term_cluster(project_id, entity_class);

-- Update schema version
UPDATE schema_meta SET value = '10' WHERE key = 'schema_version';
