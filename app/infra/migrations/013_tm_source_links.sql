-- Migration 013: Add source links to tm_entry for is_noise synchronization
-- Date: 2026-02-12
-- Purpose: Enable bidirectional sync of is_noise between Lemma/TermCluster and TMEntry

-- Add foreign key columns to link TMEntry back to source entities
ALTER TABLE tm_entry ADD COLUMN lemma_id INTEGER;
ALTER TABLE tm_entry ADD COLUMN cluster_id INTEGER;
ALTER TABLE tm_entry ADD COLUMN ngram_id INTEGER;

-- Create indexes for efficient lookups
CREATE INDEX IF NOT EXISTS idx_tm_entry_lemma ON tm_entry(lemma_id) WHERE lemma_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tm_entry_cluster ON tm_entry(cluster_id) WHERE cluster_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tm_entry_ngram ON tm_entry(ngram_id) WHERE ngram_id IS NOT NULL;

-- Backfill existing TMEntry records with source_id
-- Match by project_id + kind + src_norm (normalized text is unique key)
-- For lemmas:
UPDATE tm_entry SET lemma_id = (
    SELECT lemma.lemma_id
    FROM lemma
    WHERE lemma.project_id = tm_entry.project_id
      AND lemma.norm_text = tm_entry.src_norm
    LIMIT 1
)
WHERE tm_entry.kind = 'lemma'
  AND tm_entry.lemma_id IS NULL;

-- For term clusters:
UPDATE tm_entry SET cluster_id = (
    SELECT term_cluster.cluster_id
    FROM term_cluster
    WHERE term_cluster.project_id = tm_entry.project_id
      AND term_cluster.norm_text = tm_entry.src_norm
    LIMIT 1
)
WHERE tm_entry.kind = 'term_cluster'
  AND tm_entry.cluster_id IS NULL;

-- Sync is_noise from source to TMEntry (make TMEntry reflect current source state)
-- For lemmas:
UPDATE tm_entry SET is_noise = (
    SELECT lemma.is_noise
    FROM lemma
    WHERE lemma.lemma_id = tm_entry.lemma_id
)
WHERE tm_entry.kind = 'lemma'
  AND tm_entry.lemma_id IS NOT NULL;

-- For term clusters:
UPDATE tm_entry SET is_noise = (
    SELECT term_cluster.is_noise
    FROM term_cluster
    WHERE term_cluster.cluster_id = tm_entry.cluster_id
)
WHERE tm_entry.kind = 'term_cluster'
  AND tm_entry.cluster_id IS NOT NULL;

-- Update schema version
UPDATE schema_meta SET value = '13' WHERE key = 'schema_version';
