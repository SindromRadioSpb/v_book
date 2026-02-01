-- Migration 002: Term Extraction & Clustering (M5+)
-- Extends ngram tables for:
-- - N-grams up to n=5 (for NP chunks)
-- - Canonicalization (he_canonical, lemma_phrase)
-- - Additional association measures (LLR, Dice)
-- - Term clustering
-- - Termhood metrics (TF-IDF, weirdness vs general corpus)

-- =================================================================
-- 1. Extend ngram table for M5+
-- =================================================================

-- Add columns to ngram (if not exists pattern)
-- SQLite doesn't support IF NOT EXISTS for ALTER TABLE, but we handle it via migration tracking

ALTER TABLE ngram ADD COLUMN he_canonical TEXT;
ALTER TABLE ngram ADD COLUMN lemma_phrase TEXT;
ALTER TABLE ngram ADD COLUMN source_kind TEXT DEFAULT 'ngram' CHECK(source_kind IN ('ngram', 'np'));

-- Update constraint to allow n=2,3,4,5
-- SQLite can't alter constraints, so we recreate via temp table
CREATE TABLE ngram_new (
  ngram_id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES dict_project(project_id) ON DELETE CASCADE,
  n INTEGER NOT NULL CHECK(n IN (2,3,4,5)),
  surface_text TEXT NOT NULL,
  he_canonical TEXT,
  lemma_phrase TEXT,
  source_kind TEXT DEFAULT 'ngram' CHECK(source_kind IN ('ngram', 'np')),
  pattern_type TEXT,
  pos_pattern TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE(project_id, n, surface_text, source_kind)
);

INSERT INTO ngram_new SELECT
  ngram_id, project_id, n, surface_text,
  NULL, NULL, 'ngram',
  pattern_type, pos_pattern, created_at
FROM ngram;

DROP TABLE ngram;
ALTER TABLE ngram_new RENAME TO ngram;

-- Recreate indexes
CREATE INDEX IF NOT EXISTS idx_ngram_project ON ngram(project_id);
CREATE INDEX IF NOT EXISTS idx_ngram_canonical ON ngram(project_id, he_canonical);
CREATE INDEX IF NOT EXISTS idx_ngram_lemma_phrase ON ngram(project_id, lemma_phrase);

-- =================================================================
-- 2. Extend ngram_project_stat for additional metrics
-- =================================================================

ALTER TABLE ngram_project_stat ADD COLUMN llr_cache REAL;
ALTER TABLE ngram_project_stat ADD COLUMN dice_cache REAL;
ALTER TABLE ngram_project_stat ADD COLUMN tfidf REAL;
ALTER TABLE ngram_project_stat ADD COLUMN weirdness REAL;

CREATE INDEX IF NOT EXISTS idx_ngram_stat_llr ON ngram_project_stat(project_id, llr_cache DESC);
CREATE INDEX IF NOT EXISTS idx_ngram_stat_dice ON ngram_project_stat(project_id, dice_cache DESC);

-- =================================================================
-- 3. Create term_cluster table (M5.1)
-- =================================================================

CREATE TABLE IF NOT EXISTS term_cluster (
  cluster_id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES dict_project(project_id) ON DELETE CASCADE,

  -- Canonical key for deduplication
  canonical_key TEXT NOT NULL,

  -- Representative term (most common or shortest)
  representative_he TEXT NOT NULL,
  representative_lemma TEXT,

  -- Aggregated statistics
  freq_abs INTEGER NOT NULL DEFAULT 0 CHECK(freq_abs >= 0),
  doc_freq INTEGER NOT NULL DEFAULT 0 CHECK(doc_freq >= 0),
  members_count INTEGER NOT NULL DEFAULT 1 CHECK(members_count >= 1),

  -- Best/average scores from members
  best_pmi REAL,
  best_llr REAL,
  best_dice REAL,
  best_tscore REAL,

  -- Termhood metrics (M5.4)
  tfidf REAL,
  weirdness REAL,

  -- Metadata
  source_kinds TEXT,  -- Comma-separated: 'ngram,np'
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

  UNIQUE(project_id, canonical_key)
);

CREATE INDEX IF NOT EXISTS idx_cluster_project ON term_cluster(project_id);
CREATE INDEX IF NOT EXISTS idx_cluster_freq ON term_cluster(project_id, freq_abs DESC);
CREATE INDEX IF NOT EXISTS idx_cluster_pmi ON term_cluster(project_id, best_pmi DESC);
CREATE INDEX IF NOT EXISTS idx_cluster_llr ON term_cluster(project_id, best_llr DESC);
CREATE INDEX IF NOT EXISTS idx_cluster_weirdness ON term_cluster(project_id, weirdness DESC);

-- =================================================================
-- 4. Create term_cluster_member mapping table (M5.1)
-- =================================================================

CREATE TABLE IF NOT EXISTS term_cluster_member (
  cluster_id INTEGER NOT NULL REFERENCES term_cluster(cluster_id) ON DELETE CASCADE,
  ngram_id INTEGER NOT NULL REFERENCES ngram(ngram_id) ON DELETE CASCADE,

  -- Member contribution to cluster
  member_freq_abs INTEGER NOT NULL DEFAULT 0,
  member_doc_freq INTEGER NOT NULL DEFAULT 0,

  PRIMARY KEY(cluster_id, ngram_id)
);

CREATE INDEX IF NOT EXISTS idx_cluster_member_ngram ON term_cluster_member(ngram_id);

-- =================================================================
-- 5. Add general corpus support (M5.4)
-- =================================================================

-- Add flag to dict_project to mark as general corpus
ALTER TABLE dict_project ADD COLUMN is_general_corpus INTEGER DEFAULT 0 CHECK(is_general_corpus IN (0,1));

-- Track which general corpus a project uses for termhood
ALTER TABLE dict_project ADD COLUMN general_corpus_id INTEGER REFERENCES dict_project(project_id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_project_general ON dict_project(is_general_corpus);

-- =================================================================
-- 6. Update term_fts for cluster search (optional but recommended)
-- =================================================================

-- term_fts already exists, extend it to include clusters
-- No schema change needed - just insert clusters with kind='cluster' in service layer

-- =================================================================
-- Migration complete
-- =================================================================
