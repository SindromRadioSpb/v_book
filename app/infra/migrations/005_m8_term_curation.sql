-- Migration 005: Term Curation (M8)
-- Adds curation workflow fields to term_cluster table:
-- - curation_status: auto / needs_review / approved / rejected
-- - pinned_translation: user-selected translation override
-- - pinned_example: user-selected example sentence
-- - curation_notes: curator comments
-- - curated_at: timestamp of last curation action
-- - curated_by: curator identifier (user/system)

-- Note: Alias management and stopwords already exist via:
-- - TermAlias (term_alias table)
-- - StopwordSet + StopwordItem (stopword_set, stopword_item tables)

-- =================================================================
-- 1. Add curation fields to term_cluster
-- =================================================================

-- Curation status workflow
ALTER TABLE term_cluster ADD COLUMN curation_status TEXT DEFAULT 'auto'
  CHECK(curation_status IN ('auto', 'needs_review', 'approved', 'rejected'));

-- Pinned translation (overrides TM/Dict lookup for this term)
ALTER TABLE term_cluster ADD COLUMN pinned_translation TEXT;
ALTER TABLE term_cluster ADD COLUMN pinned_translation_lang TEXT DEFAULT 'ru';

-- Pinned example sentence (for term card display)
ALTER TABLE term_cluster ADD COLUMN pinned_example_sent_id INTEGER
  REFERENCES document_sentence(sentence_id) ON DELETE SET NULL;

-- Curation metadata
ALTER TABLE term_cluster ADD COLUMN curation_notes TEXT;
ALTER TABLE term_cluster ADD COLUMN curated_at TEXT;
ALTER TABLE term_cluster ADD COLUMN curated_by TEXT;

-- Index for review queue queries
CREATE INDEX IF NOT EXISTS idx_cluster_curation_status
  ON term_cluster(project_id, curation_status);

CREATE INDEX IF NOT EXISTS idx_cluster_needs_review
  ON term_cluster(project_id, curation_status, freq_abs DESC)
  WHERE curation_status = 'needs_review';

CREATE INDEX IF NOT EXISTS idx_cluster_approved
  ON term_cluster(project_id, curation_status, freq_abs DESC)
  WHERE curation_status = 'approved';

-- =================================================================
-- 2. Add term_cluster_stopword mapping (optional, for explicit stopword tracking)
-- =================================================================

-- Note: StopwordItem already exists and can store lemmas/surfaces.
-- For M8, we'll use StopwordItem to mark terms as stopwords.
-- No new table needed - just use existing stopword_item with lemma_text or surface.

-- =================================================================
-- Update schema version
-- =================================================================

UPDATE schema_meta SET value = '5' WHERE key = 'schema_version';

-- =================================================================
-- Migration complete
-- =================================================================

-- Usage Notes:
-- 1. curation_status workflow:
--    - 'auto': Default, auto-extracted, not reviewed
--    - 'needs_review': Flagged by system or user for manual review
--    - 'approved': Manually approved by curator
--    - 'rejected': Marked as not a term (noise)
--
-- 2. pinned_translation:
--    - Overrides TM/Dict lookup for this specific term
--    - Used in TranslationService.resolve_translation() if present
--
-- 3. pinned_example:
--    - References document_sentence.sent_id
--    - Used in term card display for context example
--
-- 4. Stopwords:
--    - Use existing StopwordItem table
--    - Add entry with lemma_text = term canonical_key
--    - TermExtractionService should filter stopwords during extraction
