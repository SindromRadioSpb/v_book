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

### Implemented bounded hardening

Current implementation now enforces this with:

- `speech_hash`
  - pronunciation-aware identity of the current spoken payload
  - used to reject stale playback fallback for rows whose `norm_text` still
    matches but pronunciation state has changed
- `input_hash`
  - exact provider/request cache identity
  - used to prevent false cache hits when provider/voice/speed/format request
    parameters or pronunciation payload changed

- content-addressed row identity
  - canonical persisted identity is now `(lang, input_hash)` for rows that
    carry a real request hash
  - multiple rows may legitimately coexist for the same legacy
    `(lang, norm_text, voice_id, speed, provider)` lookup key when the spoken
    payload changes over time

Compatibility boundary:

- old hash-less/legacy rows remain readable via bounded fallback
- runtime cache reuse and playback selection must prefer `input_hash` /
  `speech_hash` matches over the old weak lookup key
- a legacy norm/provider match alone is no longer treated as canonical cache
  identity

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

## G. Operator governance and observability contract

The repo now exposes a dedicated, read-only operator surface for heavy derived
project data:

- `ProjectDashboard -> Data Governance`
- service contract: `app/services/derived_artifact_governance_service.py`

This surface exists to answer:

- which derived tables are inevitably large,
- which ones are growing as operational telemetry,
- which values can be measured online without turning the UI into a heavy query
  launcher.

### Online metric rules

#### Exact online counts are allowed only where they stay affordable

Current online governance may use exact project-scoped counts for:

- `lemma_doc_stat`
- `lemma_project_stat`
- `processor_run`
- `run_error`

These are still read-only and background-loaded.

#### Snapshot volume must reuse the readiness aggregate

For large reference projects, exact project-scoped `sentence_nlp_snapshot` row
counts are too expensive for the normal operator UX.

Therefore the online governance surface must:

- reuse `SnapshotReadinessService`
- show snapshot volume/coverage from its aggregate
- avoid a second naïve exact snapshot-row-count query

This is intentional. It keeps the operator surface useful on huge DBs without
quietly reopening a heavy validation path.

#### Deferred acceleration options are preserved, not active

The current online contract is intentionally accepted as:

- on-demand
- background-loaded
- honest about bounded validation rather than artificially "instant"

Future acceleration options are preserved in the roadmap, but must stay
deferred until the current latency becomes a real workflow blocker:

- low-risk query/cache polish for modest wins only
- preferred future path: per-document snapshot stats
- higher-risk fallback: project-level materialized summary

If per-document or project-level persisted stats are ever introduced, they must
ship together with an explicit rebuild/verify/repair contract. Faster but
unverifiable summary data is not acceptable for this layer.

### UI contract

The governance surface is:

- observational only
- background-loaded
- on-demand, not auto-loaded in the dashboard table
- not a retention/cleanup tool
- not a production-approval signal

It may surface:

- exact project counts where affordable
- ownership/lifecycle notes
- latest coverage/backfill contract notes already established elsewhere

It must not:

- start backfill
- compact or delete data
- trigger heavy validation implicitly

### Current limitations

- project-scoped per-table byte accounting is not part of the live UI contract
- if future runtime environments expose safe table-size primitives cheaply, that
  can be added later
- telemetry retention is now an explicit operator path, but only for
  `processor_run` / `run_error`:
  - service: `app/services/project_telemetry_retention_service.py`
  - CLI: `scripts/prune_project_telemetry.py`
  - dry-run is the default
  - `--apply` requires `--confirm-project-id`
  - only successful rows with empty note metadata are prunable
  - recent successful rows, noted evidence rows, and all non-ok rows are preserved
- governance/reporting now surfaces explicit maintenance modes for the remaining
  large derived artifacts:
  - `lemma_doc_stat` -> `reset_rebuild_only`
  - `lemma_project_stat` -> `reset_rebuild_only`
  - `sentence_nlp_snapshot` -> `reset_rebuild_only`
  - `processor_run` -> `retention_available`
  - `run_error` -> `retention_with_parent_runs`
- this means:
  - telemetry cleanup is actionable and previewable
  - large project-owned derived tables are intentionally not treated as
    age-prune candidates
  - if storage pressure becomes real for those tables, the correct follow-up is
    an explicit project-level reset/rebuild workflow, not incremental cleanup
  - reference-scale rebuilds should use
    `scripts/process_reference_corpus.py --project-id <id> --reprocess-all`
    rather than any ad-hoc row deletion path
  - governance UI now exposes that rebuild path as a copyable CLI hint for
    `reset_rebuild_only` artifacts on reference projects

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

### Requirement C. Audio-cache hardening is now implemented

The bounded audio-cache hardening requirement is now implemented:

- `audio_asset` remains global
- effective synthesis identity is now persisted through `speech_hash` and
  `input_hash`
- canonical persisted row identity is `(lang, input_hash)` for hashed rows
- sentence-owned pronunciation rows are still not treated as globally reusable
  cache data

Future follow-up remains possible, but no longer at the weak-key compatibility
stage.
