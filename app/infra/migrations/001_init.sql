PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- -----------------------
-- Schema meta
-- -----------------------
CREATE TABLE IF NOT EXISTS schema_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
INSERT OR IGNORE INTO schema_meta(key, value) VALUES ('schema_version', '1');

-- -----------------------
-- Library / Projects / Corpora
-- -----------------------
CREATE TABLE IF NOT EXISTS library (
  library_id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS dict_project (
  project_id INTEGER PRIMARY KEY,
  library_id INTEGER NOT NULL REFERENCES library(library_id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT,
  src_lang TEXT NOT NULL DEFAULT 'he',
  tgt_lang TEXT NOT NULL DEFAULT 'ru',

  nlp_engine TEXT NOT NULL DEFAULT 'stanza',
  nlp_engine_version TEXT,

  -- MWE thresholds defaults
  mwe_min_freq INTEGER NOT NULL DEFAULT 3,
  mwe_min_pmi REAL NOT NULL DEFAULT 3.0,
  mwe_min_tscore REAL NOT NULL DEFAULT 2.0,
  mwe_max_n INTEGER NOT NULL DEFAULT 3 CHECK(mwe_max_n IN (2,3)),

  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE(library_id, name)
);

CREATE TRIGGER IF NOT EXISTS trg_dict_project_updated_at
AFTER UPDATE ON dict_project
FOR EACH ROW
BEGIN
  UPDATE dict_project
  SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
  WHERE project_id = NEW.project_id;
END;

CREATE TABLE IF NOT EXISTS source_corpus (
  corpus_id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES dict_project(project_id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT,
  watch_folder_path TEXT, -- optional folder watcher
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE(project_id, name)
);

-- -----------------------
-- Documents
-- -----------------------
CREATE TABLE IF NOT EXISTS source_document (
  doc_id INTEGER PRIMARY KEY,
  corpus_id INTEGER NOT NULL REFERENCES source_corpus(corpus_id) ON DELETE CASCADE,

  file_path TEXT NOT NULL,
  file_name TEXT NOT NULL,
  file_ext TEXT NOT NULL,
  file_size_bytes INTEGER NOT NULL DEFAULT 0,

  sha256 TEXT NOT NULL,
  imported_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  processed_at TEXT,

  -- For updates: keep last known mtime
  file_mtime_utc TEXT,

  status TEXT NOT NULL DEFAULT 'imported'
    CHECK(status IN ('imported','queued','processing','processed','failed')),
  error_message TEXT,

  UNIQUE(corpus_id, sha256)
);

CREATE TABLE IF NOT EXISTS document_text (
  doc_id INTEGER PRIMARY KEY REFERENCES source_document(doc_id) ON DELETE CASCADE,
  raw_text TEXT,
  cleaned_text TEXT,
  ocr_used INTEGER NOT NULL DEFAULT 0 CHECK(ocr_used IN (0,1))
);

CREATE TABLE IF NOT EXISTS document_sentence (
  sentence_id INTEGER PRIMARY KEY,
  doc_id INTEGER NOT NULL REFERENCES source_document(doc_id) ON DELETE CASCADE,
  sent_index INTEGER NOT NULL,
  text TEXT NOT NULL,
  UNIQUE(doc_id, sent_index)
);

-- -----------------------
-- FTS5: sentence search (concordance)
-- -----------------------
CREATE VIRTUAL TABLE IF NOT EXISTS sentence_fts USING fts5(
  text,
  doc_id UNINDEXED,
  sentence_id UNINDEXED,
  tokenize = 'unicode61 remove_diacritics 1'
);

CREATE TRIGGER IF NOT EXISTS trg_sentence_ai
AFTER INSERT ON document_sentence
BEGIN
  INSERT INTO sentence_fts(text, doc_id, sentence_id)
  VALUES (NEW.text, NEW.doc_id, NEW.sentence_id);
END;

CREATE TRIGGER IF NOT EXISTS trg_sentence_ad
AFTER DELETE ON document_sentence
BEGIN
  DELETE FROM sentence_fts WHERE sentence_id = OLD.sentence_id;
END;

CREATE TRIGGER IF NOT EXISTS trg_sentence_au
AFTER UPDATE OF text ON document_sentence
BEGIN
  UPDATE sentence_fts
  SET text = NEW.text, doc_id = NEW.doc_id
  WHERE sentence_id = NEW.sentence_id;
END;

-- -----------------------
-- Normalization aliases
-- -----------------------
CREATE TABLE IF NOT EXISTS term_alias (
  alias_id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES dict_project(project_id) ON DELETE CASCADE,
  variant TEXT NOT NULL,
  canonical TEXT NOT NULL,
  note TEXT,
  UNIQUE(project_id, variant)
);

-- -----------------------
-- Stopwords
-- -----------------------
CREATE TABLE IF NOT EXISTS stopword_set (
  stopset_id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES dict_project(project_id) ON DELETE CASCADE,
  name TEXT NOT NULL DEFAULT 'default',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE(project_id, name)
);

CREATE TABLE IF NOT EXISTS stopword_item (
  stopitem_id INTEGER PRIMARY KEY,
  stopset_id INTEGER NOT NULL REFERENCES stopword_set(stopset_id) ON DELETE CASCADE,
  surface TEXT,
  lemma_text TEXT,
  lemma_id INTEGER,
  reason TEXT,
  CHECK(
    (surface IS NOT NULL AND lemma_text IS NULL AND lemma_id IS NULL) OR
    (surface IS NULL AND lemma_text IS NOT NULL AND lemma_id IS NULL) OR
    (surface IS NULL AND lemma_text IS NULL AND lemma_id IS NOT NULL)
  )
);

-- -----------------------
-- Lemmas
-- -----------------------
CREATE TABLE IF NOT EXISTS lemma (
  lemma_id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES dict_project(project_id) ON DELETE CASCADE,
  lemma_text TEXT NOT NULL,
  pos TEXT,
  morph_json TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE(project_id, lemma_text)
);

CREATE TABLE IF NOT EXISTS lemma_doc_stat (
  project_id INTEGER NOT NULL REFERENCES dict_project(project_id) ON DELETE CASCADE,
  doc_id INTEGER NOT NULL REFERENCES source_document(doc_id) ON DELETE CASCADE,
  lemma_id INTEGER NOT NULL REFERENCES lemma(lemma_id) ON DELETE CASCADE,
  freq_abs INTEGER NOT NULL CHECK(freq_abs >= 0),
  sample_sentence_id INTEGER REFERENCES document_sentence(sentence_id) ON DELETE SET NULL,
  PRIMARY KEY(project_id, doc_id, lemma_id)
);

CREATE TABLE IF NOT EXISTS lemma_project_stat (
  project_id INTEGER NOT NULL REFERENCES dict_project(project_id) ON DELETE CASCADE,
  lemma_id INTEGER NOT NULL REFERENCES lemma(lemma_id) ON DELETE CASCADE,
  freq_abs INTEGER NOT NULL CHECK(freq_abs >= 0),
  doc_freq INTEGER NOT NULL DEFAULT 0 CHECK(doc_freq >= 0),
  sample_sentence_id INTEGER REFERENCES document_sentence(sentence_id) ON DELETE SET NULL,
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  PRIMARY KEY(project_id, lemma_id)
);

-- -----------------------
-- Ngrams / MWEs
-- -----------------------
CREATE TABLE IF NOT EXISTS ngram (
  ngram_id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES dict_project(project_id) ON DELETE CASCADE,
  n INTEGER NOT NULL CHECK(n IN (2,3)),
  surface_text TEXT NOT NULL,
  pattern_type TEXT,
  pos_pattern TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE(project_id, n, surface_text)
);

CREATE TABLE IF NOT EXISTS ngram_component (
  ngram_id INTEGER NOT NULL REFERENCES ngram(ngram_id) ON DELETE CASCADE,
  position INTEGER NOT NULL CHECK(position >= 0),
  lemma_id INTEGER NOT NULL REFERENCES lemma(lemma_id) ON DELETE CASCADE,
  surface_token TEXT,
  PRIMARY KEY(ngram_id, position)
);

CREATE TABLE IF NOT EXISTS ngram_doc_stat (
  project_id INTEGER NOT NULL REFERENCES dict_project(project_id) ON DELETE CASCADE,
  doc_id INTEGER NOT NULL REFERENCES source_document(doc_id) ON DELETE CASCADE,
  ngram_id INTEGER NOT NULL REFERENCES ngram(ngram_id) ON DELETE CASCADE,
  freq_abs INTEGER NOT NULL CHECK(freq_abs >= 0),
  sample_sentence_id INTEGER REFERENCES document_sentence(sentence_id) ON DELETE SET NULL,
  PRIMARY KEY(project_id, doc_id, ngram_id)
);

CREATE TABLE IF NOT EXISTS ngram_project_stat (
  project_id INTEGER NOT NULL REFERENCES dict_project(project_id) ON DELETE CASCADE,
  ngram_id INTEGER NOT NULL REFERENCES ngram(ngram_id) ON DELETE CASCADE,
  freq_abs INTEGER NOT NULL CHECK(freq_abs >= 0),
  doc_freq INTEGER NOT NULL DEFAULT 0 CHECK(doc_freq >= 0),
  pmi_cache REAL,
  tscore_cache REAL,
  sample_sentence_id INTEGER REFERENCES document_sentence(sentence_id) ON DELETE SET NULL,
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  PRIMARY KEY(project_id, ngram_id)
);

-- -----------------------
-- Term cards / curation
-- -----------------------
CREATE TABLE IF NOT EXISTS term_card (
  term_id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES dict_project(project_id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK(kind IN ('lemma','ngram')),
  lemma_id INTEGER REFERENCES lemma(lemma_id) ON DELETE CASCADE,
  ngram_id INTEGER REFERENCES ngram(ngram_id) ON DELETE CASCADE,

  status TEXT NOT NULL DEFAULT 'auto'
    CHECK(status IN ('auto','needs_review','approved','rejected')),

  quality_score INTEGER CHECK(quality_score BETWEEN 0 AND 100),
  notes TEXT,
  pinned_sentence_id INTEGER REFERENCES document_sentence(sentence_id) ON DELETE SET NULL,

  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

  CHECK(
    (kind='lemma' AND lemma_id IS NOT NULL AND ngram_id IS NULL) OR
    (kind='ngram' AND lemma_id IS NULL AND ngram_id IS NOT NULL)
  ),
  UNIQUE(project_id, kind, lemma_id, ngram_id)
);

CREATE TRIGGER IF NOT EXISTS trg_term_card_updated_at
AFTER UPDATE ON term_card
FOR EACH ROW
BEGIN
  UPDATE term_card
  SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
  WHERE term_id = NEW.term_id;
END;

-- -----------------------
-- Translation memory
-- -----------------------
CREATE TABLE IF NOT EXISTS translation_memory (
  tm_id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES dict_project(project_id) ON DELETE CASCADE,

  lemma_id INTEGER REFERENCES lemma(lemma_id) ON DELETE CASCADE,
  ngram_id INTEGER REFERENCES ngram(ngram_id) ON DELETE CASCADE,

  translation TEXT NOT NULL,
  source TEXT NOT NULL CHECK(source IN ('auto','user','import')),
  confidence REAL,
  is_override INTEGER NOT NULL DEFAULT 0 CHECK(is_override IN (0,1)),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

  CHECK(
    (lemma_id IS NOT NULL AND ngram_id IS NULL) OR
    (lemma_id IS NULL AND ngram_id IS NOT NULL)
  ),
  UNIQUE(project_id, lemma_id, ngram_id)
);

-- -----------------------
-- Term search materialization + FTS5 (dictionary search)
-- App layer обязана поддерживать актуальность term_search
-- -----------------------
CREATE TABLE IF NOT EXISTS term_search (
  term_rowid INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES dict_project(project_id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK(kind IN ('lemma','ngram')),
  lemma_id INTEGER,
  ngram_id INTEGER,
  he_term TEXT NOT NULL,
  ru_translation TEXT,
  notes TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS term_fts USING fts5(
  he_term,
  ru_translation,
  notes,
  project_id UNINDEXED,
  kind UNINDEXED,
  lemma_id UNINDEXED,
  ngram_id UNINDEXED,
  term_rowid UNINDEXED,
  tokenize = 'unicode61 remove_diacritics 1'
);

CREATE TRIGGER IF NOT EXISTS trg_term_search_ai
AFTER INSERT ON term_search
BEGIN
  INSERT INTO term_fts(he_term, ru_translation, notes, project_id, kind, lemma_id, ngram_id, term_rowid)
  VALUES (NEW.he_term, NEW.ru_translation, NEW.notes, NEW.project_id, NEW.kind, NEW.lemma_id, NEW.ngram_id, NEW.term_rowid);
END;

CREATE TRIGGER IF NOT EXISTS trg_term_search_ad
AFTER DELETE ON term_search
BEGIN
  DELETE FROM term_fts WHERE term_rowid = OLD.term_rowid;
END;

CREATE TRIGGER IF NOT EXISTS trg_term_search_au
AFTER UPDATE ON term_search
BEGIN
  UPDATE term_fts
  SET he_term = NEW.he_term,
      ru_translation = NEW.ru_translation,
      notes = NEW.notes,
      project_id = NEW.project_id,
      kind = NEW.kind,
      lemma_id = NEW.lemma_id,
      ngram_id = NEW.ngram_id
  WHERE term_rowid = NEW.term_rowid;
END;

-- -----------------------
-- Processing audit / errors
-- -----------------------
CREATE TABLE IF NOT EXISTS processor_run (
  run_id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES dict_project(project_id) ON DELETE CASCADE,
  started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  finished_at TEXT,
  engine TEXT NOT NULL,
  engine_version TEXT,
  docs_processed INTEGER NOT NULL DEFAULT 0,
  tokens_total INTEGER NOT NULL DEFAULT 0,
  lemmas_total INTEGER NOT NULL DEFAULT 0,
  ngrams_total INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'running' CHECK(status IN ('running','ok','failed')),
  note TEXT
);

CREATE TABLE IF NOT EXISTS run_error (
  error_id INTEGER PRIMARY KEY,
  run_id INTEGER NOT NULL REFERENCES processor_run(run_id) ON DELETE CASCADE,
  doc_id INTEGER REFERENCES source_document(doc_id) ON DELETE SET NULL,
  stage TEXT NOT NULL,
  message TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- -----------------------
-- Task queue for indexing
-- -----------------------
CREATE TABLE IF NOT EXISTS task_queue (
  task_id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES dict_project(project_id) ON DELETE CASCADE,
  doc_id INTEGER REFERENCES source_document(doc_id) ON DELETE CASCADE,

  op TEXT NOT NULL CHECK(op IN ('add','update','remove')),
  status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','done','failed','canceled')),
  priority INTEGER NOT NULL DEFAULT 100,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  started_at TEXT,
  finished_at TEXT,
  error_message TEXT
);

-- -----------------------
-- Snapshots
-- -----------------------
CREATE TABLE IF NOT EXISTS project_snapshot (
  snapshot_id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES dict_project(project_id) ON DELETE CASCADE,
  label TEXT NOT NULL,
  note TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  engine TEXT NOT NULL,
  engine_version TEXT
);

-- -----------------------
-- Indexes
-- -----------------------
CREATE INDEX IF NOT EXISTS idx_doc_corpus_status ON source_document(corpus_id, status);
CREATE INDEX IF NOT EXISTS idx_sentence_doc ON document_sentence(doc_id, sent_index);

CREATE INDEX IF NOT EXISTS idx_lemma_project_text ON lemma(project_id, lemma_text);
CREATE INDEX IF NOT EXISTS idx_lemma_doc_doc ON lemma_doc_stat(doc_id);
CREATE INDEX IF NOT EXISTS idx_lemma_proj_freq ON lemma_project_stat(project_id, freq_abs DESC, lemma_id);

CREATE INDEX IF NOT EXISTS idx_ngram_project_surface ON ngram(project_id, n, surface_text);
CREATE INDEX IF NOT EXISTS idx_ngram_proj_freq ON ngram_project_stat(project_id, freq_abs DESC, ngram_id);

CREATE INDEX IF NOT EXISTS idx_tm_lookup_lemma ON translation_memory(project_id, lemma_id) WHERE lemma_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tm_lookup_ngram ON translation_memory(project_id, ngram_id) WHERE ngram_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_term_card_status ON term_card(project_id, status);
CREATE INDEX IF NOT EXISTS idx_task_queue_status ON task_queue(project_id, status, priority, created_at);
