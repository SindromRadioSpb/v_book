# Performance Optimization Plan - 2026-03-08

## Scope

This document captures the approved performance findings and the next patch series after the processed-document deletion fix on the live hewiki test database:

- DB path: `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`
- reference test file:
  `E:\andasai_mechonot\Подготовка к экзамену\Материаловедение\124-203 для программы.docx`

## Confirmed Findings

### 1. Real root cause of slow processed-document delete

The dominant slowdown on the live DB was not only lemma cleanup.

After NLP, document deletion removed `source_document`, which cascaded into
`document_sentence`. SQLite then had to execute `ON DELETE SET NULL` / `CASCADE`
checks against child tables keyed by `document_sentence.sentence_id`.

The problematic columns were:

- `lemma_doc_stat.sample_sentence_id`
- `lemma_project_stat.sample_sentence_id`
- `ngram_doc_stat.sample_sentence_id`
- `ngram_project_stat.sample_sentence_id`
- `term_card.pinned_sentence_id`
- `term_cluster.pinned_example_sent_id`

On the live DB, `EXPLAIN QUERY PLAN` showed full scans for these lookups.

### 2. Live DB scale that makes the problem visible

Observed counts during audit:

- `document_sentence`: `13,387,588+`
- `lemma_doc_stat`: `104,177,038+`
- `lemma_project_stat`: `2,071,947+`

Even correct FK logic becomes too expensive when the child-side lookup columns are
not indexed and SQLite must scan the whole table repeatedly.

### 3. Why project delete looked fast

`ProjectService.delete_project()` already uses a premium fast-delete strategy:

- ensure FTS tables exist
- `PRAGMA foreign_keys=OFF`
- explicit ordered child cleanup
- one bounded commit with retry

`IngestService.delete_document()` previously did not.

### 4. Verified fix already delivered

Processed document delete now uses the same bounded strategy:

- stats cleanup first
- explicit child cleanup
- `foreign_keys=OFF` only inside the fast-delete path
- explicit delete of `sentence_pronunciation`, `lemma_doc_stat`, `ngram_doc_stat`,
  `document_text`, `document_sentence`, then `source_document`

Live repro after fix:

- NLP processing: `525` sentences, `2642` lemmas/stats
- `delete_document`: about `0.204s`
- post-delete counts for document/text/sentences/lemma stats/lemmas: all `0`

## Index Recommendations

### High priority

These indexes directly target confirmed FK scan hot spots:

- `lemma_doc_stat(sample_sentence_id)`
- `lemma_project_stat(sample_sentence_id)`
- `ngram_doc_stat(sample_sentence_id)`
- `ngram_project_stat(sample_sentence_id)`
- `term_card(pinned_sentence_id)`
- `term_cluster(pinned_example_sent_id)`

### Medium priority

These help document/project cleanup paths and related maintenance:

- `run_error(doc_id)`
- `user_dictionary_item(origin_doc_id)`
- `task_queue(doc_id)`

### Not currently urgent

The following tested paths already had adequate leading indexes:

- `document_sentence(doc_id)`
- major `tm_entry` lookup paths
- `lemma(project_id, lemma_text)`

## Technique Recommendations Beyond Indexes

### A. Replace ORM row-by-row delete/update with set-based SQL

Apply this to large-scale paths where rows are already identified by `project_id`,
`doc_id`, `lemma_id`, or similar stable keys.

Confirmed good pattern:

- one transaction per user action
- `DELETE ... WHERE ... IN (...)`
- `UPDATE ... WHERE ... IN (...)`
- optional `bindparam(..., expanding=True)` for stable ID sets

### B. Use explicit child cleanup instead of expensive FK cascades on huge tables

Use only in bounded maintenance/delete paths where the full object graph is known.

Pattern:

1. ensure auxiliary structures exist (`ensure_fts_tables`)
2. end any incidental read transaction
3. temporarily disable FKs on the active sqlite connection
4. perform explicit `SET NULL` / child deletes in dependency order
5. delete parent rows
6. commit with retry
7. restore `foreign_keys=ON`

### C. Keep long operations off the UI thread

Operations that touch any of the following should default to workers:

- `document_sentence`
- `lemma_doc_stat`
- `lemma_project_stat`
- project exchange import/export on large projects
- large translation/admin/materialization jobs

### D. Prefer deterministic checkpoint boundaries over many tiny commits

Good:

- commit once per user action
- commit once per batch/chunk checkpoint

Bad:

- commit inside per-row loops
- commit after every entity mutation in heavy paths

## Next Patch Series

### PATCH-01

Foundation:

- add schema migration for the proven missing indexes
- keep migration additive and cheap

Files:

- `app/infra/migrations/033_delete_fk_perf_indexes.sql`
- tests/docs if needed

### PATCH-02

Reprocess fast path:

- remove row-by-row deletion of old `DocumentSentence` rows in
  `ProcessService.reprocess_document()`
- use the same explicit sentence cleanup strategy as fast document delete

Files:

- `app/services/process_service.py`
- targeted regression tests

### PATCH-03

Further perf hardening candidates:

- audit `project_exchange/export_engine.py` for repeated correlated `EXISTS`
- audit large translation/admin bulk paths for unnecessary per-row commits
- convert additional heavy maintenance paths to explicit set-based SQL where justified

## Immediate Priority Order

1. add the missing FK-related indexes
2. fix `reprocess_document()` old-sentence cleanup path
3. audit export/translation bulk paths

## Risk Notes

- `foreign_keys=OFF` must remain limited to tightly bounded maintenance paths
- orphaned `lemma` rows must not be left behind because several stats/coverage paths
  still count directly from `lemma`
- every new fast path must be backed by targeted regression tests
