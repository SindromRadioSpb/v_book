-- Migration 032: fix sentence_fts triggers to use rowid instead of UNINDEXED column
-- Date: 2026-03-07
--
-- Bug: trg_sentence_ad used "DELETE FROM sentence_fts WHERE sentence_id = OLD.sentence_id"
--      sentence_id is declared UNINDEXED in the FTS5 DDL, so every deletion required
--      a full scan of the entire sentence_fts table (~13M rows).
--      Even deleting a single sentence triggered an O(13M) FTS scan.
--
-- Root cause: the FTS row for sentence_id=N was always inserted with rowid=N
--      (because sentences are inserted sequentially and both auto-increments match),
--      so using "WHERE rowid = OLD.sentence_id" is both correct and O(log N).
--
-- Also fix: trg_sentence_ai now sets rowid = NEW.sentence_id explicitly,
--      making the rowid=sentence_id invariant explicit instead of accidental.
--
-- BEFORE: delete 1 sentence → O(13M) FTS scan → seconds per deletion
-- AFTER:  delete 1 sentence → O(log N) FTS rowid lookup → microseconds

-- Fix INSERT trigger: set rowid = sentence_id explicitly
DROP TRIGGER IF EXISTS trg_sentence_ai;
CREATE TRIGGER IF NOT EXISTS trg_sentence_ai
AFTER INSERT ON document_sentence
BEGIN
    INSERT INTO sentence_fts(rowid, text, doc_id, sentence_id)
    VALUES (NEW.sentence_id, NEW.text, NEW.doc_id, NEW.sentence_id);
END;

-- Fix DELETE trigger: use rowid (indexed) instead of sentence_id (UNINDEXED)
DROP TRIGGER IF EXISTS trg_sentence_ad;
CREATE TRIGGER IF NOT EXISTS trg_sentence_ad
AFTER DELETE ON document_sentence
BEGIN
    DELETE FROM sentence_fts WHERE rowid = OLD.sentence_id;
END;

-- Fix UPDATE trigger similarly
DROP TRIGGER IF EXISTS trg_sentence_au;
CREATE TRIGGER IF NOT EXISTS trg_sentence_au
AFTER UPDATE OF text ON document_sentence
BEGIN
    DELETE FROM sentence_fts WHERE rowid = OLD.sentence_id;
    INSERT INTO sentence_fts(rowid, text, doc_id, sentence_id)
    VALUES (NEW.sentence_id, NEW.text, NEW.doc_id, NEW.sentence_id);
END;

UPDATE schema_meta SET value = '32' WHERE key = 'schema_version';
