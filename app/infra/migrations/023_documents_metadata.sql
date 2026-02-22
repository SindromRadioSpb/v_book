-- Migration 023: Add metadata fields to source_document
-- Fields: tag, link_url, level (aleph/bet/gimel/he), topic
-- All fields are nullable (additive, backward-compatible).

-- Add tag column (free-text label, max 200 chars enforced at service layer)
ALTER TABLE source_document ADD COLUMN tag TEXT;

-- Add link_url column (http/https URL, validated at service layer)
ALTER TABLE source_document ADD COLUMN link_url TEXT;

-- Add level column with CHECK constraint for fixed enum
ALTER TABLE source_document ADD COLUMN level TEXT
    CHECK (level IS NULL OR level IN ('aleph', 'bet', 'gimel', 'he'));

-- Add topic column (free-text, max 500 chars enforced at service layer)
ALTER TABLE source_document ADD COLUMN topic TEXT;

-- Index for filtering/sorting by level (most selective new field)
CREATE INDEX IF NOT EXISTS idx_doc_level ON source_document(level)
    WHERE level IS NOT NULL;

-- Index for tag filtering
CREATE INDEX IF NOT EXISTS idx_doc_tag ON source_document(tag)
    WHERE tag IS NOT NULL;

-- Index for topic filtering
CREATE INDEX IF NOT EXISTS idx_doc_topic ON source_document(topic)
    WHERE topic IS NOT NULL;

UPDATE schema_meta SET value = '23' WHERE key = 'schema_version';
