# Project Data vs Global Cache Lifecycle Contract

## Purpose

This document defines which data is project-owned and must disappear when a
document/project is deleted, and which data may safely live in a global cache
and be reused across projects and sessions.

It exists to prevent three classes of bugs:

1. stale project-scoped data reappearing after delete/reimport
2. incorrect cache reuse across unrelated projects
3. weak cache keys that reuse outdated pronunciation/audio payloads

## Core Rule

Project-scoped business data and global derived cache are different layers and
must not be mixed.

### Project-owned data

These rows belong to one project/document/sentence lifecycle and must be removed
when the owning entity is removed:

- `source_corpus`
- `source_document`
- `document_text`
- `document_sentence`
- `sentence_pronunciation`
- `lemma`
- `lemma_doc_stat`
- `lemma_project_stat`
- `ngram`
- `ngram_doc_stat`
- `ngram_project_stat`
- `term_cluster`
- `term_card`
- `task_queue`
- `run_error` rows linked to deleted documents
- project-scoped TM / dictionary / snapshots / processing rows

### Global reusable cache

Only deterministic derived artifacts that do not semantically belong to one
project may be reused globally.

Current examples:

- `pronunciation_entry`
  - lexical/global metadata keyed by `lang + src_norm`
  - not project-owned
- `audio_asset`
  - operational cache for generated audio artifacts
  - not exchanged with projects

## Current confirmed behavior

### Correct project-owned layer

- `sentence_pronunciation` is keyed by `sentence_id`
- therefore it is sentence/project-owned and must be deleted with the sentence
- this is the correct ownership model

### Current global cache behavior

- `pronunciation_entry` is global and intentionally excluded from project bundle copy
- `audio_asset` is global and intentionally treated as operational cache

This matches current documentation:

- [PROJECT_EXCHANGE_AUDIO_PRONUNCIATION.md](J:\Project_Vibe\V_book\docs\PROJECT_EXCHANGE_AUDIO_PRONUNCIATION.md)
- [SENTENCES_NIQQUD.md](J:\Project_Vibe\V_book\docs\SENTENCES_NIQQUD.md)

## Confirmed bugs that motivated this contract

### 1. Sentence rows existed but were invisible

Root cause:

- `ProcessService.process_document()` inserted `document_sentence` rows without
  filling denormalized `corpus_id`
- `SentencesWorkspaceService.list_sentences()` filtered by `document_sentence.corpus_id`
- result: `count_sentences()` reported correct totals from `source_document.sentence_count`,
  but `list_sentences()` returned zero rows

Fix:

- write `document_sentence.corpus_id` during NLP processing
- backfill legacy rows with migration `034`

### 2. Stale persisted document filter hid valid sentences

Root cause:

- `SentencesView` persisted `doc_filter_id` across sessions
- deleted/recreated projects/documents can make that `doc_id` invalid
- the old filter was restored without validating that the document still belongs
  to the same project

Fix:

- validate saved `doc_filter_id` against current project on restore
- clear it if the document no longer exists in that project

### 3. Audio/TTS can look like "deleted data came back"

This is not always a delete bug.

If a sentence/document is re-imported with the same normalized source text,
global `audio_asset` lookup may still resolve an existing cached asset, because
`audio_asset` is intentionally not project-owned.

That reuse is acceptable only if the cache key is strong enough.

## Correct future concept

## A. Ownership contract

### Project-owned layer

Must be the source of truth for:

- document structure
- sentence rows
- sentence-level pronunciation overlays
- lemma/ngram/term statistics
- project-specific translations and processing state

Delete document/project:

- remove these rows fully
- no hidden project-owned leftovers should survive as reusable cache

### Global cache layer

May store:

- deterministic derived artifacts
- expensive-to-recompute artifacts
- artifacts safe to share across projects

But only if the key fully describes the derivation input.

## B. Cache-key rule

Global cache keys must be based on derivation input, not on project identity and
not on weak UI-facing labels.

### Good key

Content-addressed key over effective synthesis input:

- language
- normalized source text
- effective pronunciation / niqqud payload hash
- provider id
- voice id
- speed
- output format
- relevant generator/model version
- sanitizer/version components

### Bad key

- `project_id`
- `doc_id`
- `sentence_id` for globally reusable audio
- plain `norm_text` only, when pronunciation can change independently

## C. Recommended audio concept

### Current risk

`audio_asset` is currently keyed too weakly for sentence-audio reuse because it
does not encode the full effective pronunciation/synthesis payload.

This creates risk of reusing audio generated from an older pronunciation state.

### Recommended target model

Keep `audio_asset` global, but strengthen it into a content-addressed cache:

- add `input_hash` / `speech_hash`
- hash should include:
  - `lang`
  - effective TTS text or SSML
  - provider id
  - voice id
  - speed
  - format
  - provider/model version if relevant

Then:

- delete project/document does **not** delete the global audio asset row/file
- project-owned rows referencing audio are removed
- re-import can reuse audio only if the effective synthesis input is identical

## D. Recommended pronunciation concept

### Lexical pronunciation

`pronunciation_entry` may remain global if its key is lexical and project-agnostic:

- `lang + src_norm`

This is appropriate for reusable lexical metadata.

### Sentence pronunciation

`sentence_pronunciation` must remain project/sentence-owned:

- key = `sentence_id`
- survives only as long as the sentence survives

If future reuse is desired, add a separate global cache keyed by sentence
`src_hash`, but do not turn the existing project-owned table into a pseudo-global layer.

## E. UI state contract

Persisted UI state that references DB entities must be validated on restore:

- saved `doc_id`
- saved `project_id`
- cached project view identity

If the entity no longer exists in the same project/context:

- clear the state
- do not silently keep stale labels or IDs

## F. Scaling rule

For large SQLite corpora:

- do not rely on heavy FK cascades over unindexed child columns
- use explicit maintenance/delete paths for huge graphs
- use set-based SQL, not row-by-row ORM loops
- use global cache only for deterministic artifacts with strong keys

## Immediate follow-up recommendations

1. Keep project-owned sentence/document/lemma cleanup strict and complete.
2. Treat `audio_asset` as global content-addressed cache, not project data.
3. Strengthen audio cache key with effective pronunciation/synthesis hash.
4. Validate persisted UI entity filters on restore.
5. Never reuse project-owned sentence-level pronunciation rows across projects.

## Approved Requirements For Next Iteration

These recommendations are now promoted to requirements for the next bounded
performance iteration.

### Requirement A. Export/import and maintenance paths must respect ownership

Any export, import, delete, reset, or backfill path must preserve the ownership
split:

- project-owned sentence/document data is copied or deleted only with the
  owning project
- global cache rows are never treated as a substitute for missing project-owned
  rows

### Requirement B. Performance optimizations must not weaken lifecycle rules

When replacing ORM loops with set-based SQL or explicit cleanup:

- do not reintroduce hidden reuse of project-owned rows
- do not keep stale entity references alive only because they are fast to reuse
- keep deterministic ordering and one bounded transaction per user action

### Requirement C. Future audio-cache hardening stays in scope

The next patch series may optimize other heavy paths first, but the future
`audio_asset` change is now a tracked requirement, not an optional idea:

- keep `audio_asset` global
- strengthen it with an effective synthesis input hash
- never treat sentence-owned pronunciation rows as globally reusable data
