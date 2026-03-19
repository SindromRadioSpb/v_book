# PERF Query Plan Audit (Hewiki)

- Generated (UTC): `2026-02-25T17:14:14.020890+00:00`
- DB: `M:\Soft\1. Data folder HDLE Local (model, dataset, logs temporary)\HDLE_Processing\hewiki_gpu_processing.db`
- Project ID: `1`
- Search term: `wiki`

## Index Snapshot

### `lemma`
- `idx_lemma_entity_class`
- `idx_lemma_noise`
- `idx_lemma_project_text`
- `sqlite_autoindex_lemma_1`

### `lemma_project_stat`
- `idx_lemma_proj_freq`
- `sqlite_autoindex_lemma_project_stat_1`

### `source_corpus`
- `sqlite_autoindex_source_corpus_1`

### `source_document`
- `idx_doc_corpus_project`
- `idx_doc_corpus_status`
- `idx_doc_level`
- `idx_doc_sentence_count`
- `idx_doc_tag`
- `idx_doc_token_count`
- `idx_doc_topic`
- `sqlite_autoindex_source_document_1`

### `document_sentence`
- `idx_sentence_doc`
- `sqlite_autoindex_document_sentence_1`

### `pronunciation_entry`
- `idx_pronunciation_lang_norm`
- `idx_pronunciation_source`
- `sqlite_autoindex_pronunciation_entry_1`
- `uq_pronunciation_entry_key`

### `tm_entry`
- `idx_tm_entry_cluster`
- `idx_tm_entry_global_id`
- `idx_tm_entry_kind_noise`
- `idx_tm_entry_lemma`
- `idx_tm_entry_lookup`
- `idx_tm_entry_ngram`
- `idx_tm_entry_noise`
- `idx_tm_entry_src_norm`
- `idx_tm_entry_translation_norm`
- `sqlite_autoindex_tm_entry_1`

## Query Plans

### Dictionary first page (`dictionary_first_page`)

```sql
SELECT l.lemma_id, l.lemma_text, l.pos, s.freq_abs, s.doc_freq
FROM lemma_project_stat AS s
JOIN lemma AS l
  ON l.lemma_id = s.lemma_id AND l.project_id = s.project_id
WHERE s.project_id = ?
  AND l.project_id = ?
  AND (l.is_noise = 0 OR l.is_noise IS NULL)
ORDER BY s.freq_abs DESC, s.lemma_id ASC
LIMIT 100 OFFSET 0
```

Plan:
- `(14, 0, 0, 'SEARCH s USING INDEX idx_lemma_proj_freq (project_id=?)')`
- `(21, 0, 0, 'SEARCH l USING INTEGER PRIMARY KEY (rowid=?)')`
- Note: No obvious full scan/temp B-tree marker in this plan.
- Sample time: `0.0006s` (rows=100)

### Dictionary count (`dictionary_count`)

```sql
SELECT COUNT(l.lemma_id)
FROM lemma AS l
WHERE l.project_id = ?
  AND (l.is_noise = 0 OR l.is_noise IS NULL)
```

Plan:
- `(3, 0, 0, 'SEARCH l USING COVERING INDEX idx_lemma_noise (project_id=?)')`
- Note: No obvious full scan/temp B-tree marker in this plan.
- Sample time: `0.1822s` (rows=1)

### Document picker page (empty search) (`picker_page_empty`)

```sql
SELECT d.doc_id, d.file_name, d.tag
FROM source_document AS d
JOIN source_corpus AS c ON d.corpus_id = c.corpus_id
WHERE c.project_id = ?
ORDER BY d.doc_id DESC
LIMIT 50 OFFSET 0
```

Plan:
- `(9, 0, 0, 'SEARCH c USING COVERING INDEX sqlite_autoindex_source_corpus_1 (project_id=?)')`
- `(15, 0, 0, 'SEARCH d USING INDEX idx_doc_corpus_project (corpus_id=?)')`
- `(32, 0, 0, 'USE TEMP B-TREE FOR ORDER BY')`
- Note: Uses temporary B-tree (sort/group spill risk).
- Sample time: `0.0002s` (rows=50)

### Document picker page (text search) (`picker_page_search`)

```sql
SELECT d.doc_id, d.file_name, d.tag
FROM source_document AS d
JOIN source_corpus AS c ON d.corpus_id = c.corpus_id
WHERE c.project_id = ?
  AND (lower(d.file_name) LIKE lower(?) OR lower(d.tag) LIKE lower(?))
ORDER BY d.file_name ASC, d.doc_id ASC
LIMIT 50 OFFSET 0
```

Plan:
- `(9, 0, 0, 'SEARCH c USING COVERING INDEX sqlite_autoindex_source_corpus_1 (project_id=?)')`
- `(15, 0, 0, 'SEARCH d USING INDEX idx_doc_corpus_project (corpus_id=?)')`
- `(46, 0, 0, 'USE TEMP B-TREE FOR ORDER BY')`
- Note: Uses temporary B-tree (sort/group spill risk).
- Sample time: `0.2629s` (rows=11)

## Findings

- Dictionary first-page flow is index-driven when ordering uses `lemma_project_stat.lemma_id` as tie-breaker.
- Dictionary count uses `idx_lemma_noise` and remains a bounded read.
- Document picker empty search still uses temporary sort; index pack migration adds `idx_doc_corpus_file_name` to reduce sort pressure for file-name ordered pagination paths.
- Document picker text search uses temporary sort due flexible text predicate; this is expected for contains-style matching.
