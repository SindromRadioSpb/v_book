# NLP Processing Checkpoint Plan

Date: 2026-03-09

## Purpose

This document saves the current implementation plan for bringing `process with NLP`
to the same engineering maturity level as staged `extract terms`, without losing
the confirmed repo context discovered during the Task 30 follow-up work.

## Confirmed entry points

- Regular-project UI path:
  - `app/ui/documents_view.py`
  - `app/ui/workers.py::ProcessWorker`
  - `app/services/process_service.py::process_document()`
- Reference-scale CLI path:
  - `scripts/process_reference_corpus.py`
  - `docs/REFERENCE_PROJECT_GUIDE.md`
- Current persistence/crash state:
  - `app/infra/sa_models.py::ProcessorRun`
  - `app/services/db_service.py::recover_from_crash()`

## Saved baseline concept

The initial concept worth preserving for later implementation was:

- add a durable DB-backed run ledger for NLP processing
- emit structured progress state, not only `(current, total, doc_name)`
- support cooperative cancel/pause/resume at deterministic boundaries
- add a dedicated extraction-grade progress dialog for regular-project NLP runs
- add a verify/refresh contract for prepared source identity if a prepared-NLP
  workflow is introduced later

## Corrected after deeper repo review

The deeper audit changes the implementation shape in several important ways.

### 1. Reference corpus must remain CLI-only

Confirmed in `docs/REFERENCE_PROJECT_GUIDE.md` and `app/ui/documents_view.py`:

- UI `Process` / `Re-process` is intentionally blocked for reference corpora
- large reference NLP processing must continue to run via
  `scripts/process_reference_corpus.py`

This means the future premium progress UI applies to regular projects first.
Reference-scale work should reuse the same run-state contract, but not re-enable
multi-hour UI writes.

### 2. First production implementation should not copy the benchmark fixture model

For `extract terms`, a prepared fixture DB is a benchmark/runtime harness tool.
For real NLP processing, the first safe production design should instead:

- process directly against the main DB
- keep write scope bounded to one document or one chunk checkpoint
- persist resumable run state in the main DB

A full copied working DB plus merge-back protocol is only a later optional design
if remote/offline processing becomes a real product requirement.

### 3. Existing legacy processing state is too weak

Current `processor_run` is not enough for staged/cancelable/resumable NLP:

- `status` only supports `running/ok/failed`
- no `last_doc_id`
- no `docs_total/docs_failed/chunks_total/chunks_completed`
- no `params_hash`
- no resume gating

Also, `DBService.recover_from_crash()` currently only knows the legacy
`running -> failed` recovery path.

### 4. UI parity should follow the extract-terms contract

The desired target is not a generic spinner. It should match the terms flow:

- stage label
- run id
- doc progress
- chunk progress
- last processed doc id
- elapsed / last activity
- bounded activity log
- pause/resume/cancel buttons
- cooperative close behavior

## Pre-implementation audit refresh (2026-03-09)

Before starting the next implementation wave, the following baseline was
re-verified against the current repo state.
This section is kept as the historical preflight captured before
`PATCH-NLP-01`.

### Docs re-read for this preflight

- `docs/REFERENCE_PROJECT_GUIDE.md`
- `docs/PERF_SCALE_AUDIT_HEWIKI_2026-03-07.md`
- `docs/PERF_IMPLEMENTATION_AUDIT.md`
- `docs/PERFORMANCE_SLO.md`
- `docs/TERM_EXTRACTION_CHUNKED_PLAN.md`

### Baseline evidence

- Targeted NLP/reference regression slice:
  - `tests/test_task12_fts_nlp.py`
  - `tests/test_reference_processing_guard.py`
  - `tests/test_process_service_remove_document_stats.py`
  - `tests/test_operations_center.py`
  - `tests/test_pipeline_throttler.py`
- Result:
  - `47 passed in 38.94s`
  - artifact: `build/logs/nlp_prework/pytest_nlp_prework.log`
- Approved DB dry-run:
  - `python scripts/process_reference_corpus.py --db-path "...hewiki_gpu_processing test.db" --project-id 1 --dry-run`
  - artifact: `build/logs/nlp_prework/process_reference_corpus_dry_run.log`
  - confirmed runtime state on `2026-03-09`:
    - project is `is_general_corpus=1`
    - `387639 / 387639` docs are already processed
    - `To process: 0`

### Additional confirmed corrections

#### 5. Resume/checkpoint proof cannot rely on the approved DB alone

Because the approved `hewiki_gpu_processing test.db` currently has no remaining
unprocessed documents, new resume/cancel/checkpoint behavior must be validated
through temporary DB fixtures or controlled sandbox slices, not by expecting a
live interrupted run on that DB.

#### 6. Migration/version truth is `schema_meta`, not `schema_version`

The current migration system reads the version from:

- `app/infra/db.py::DatabaseManager.apply_migrations()`
- `schema_meta(key='schema_version')`

Do not plan NLP migrations around a hypothetical `schema_version` table or
`PRAGMA user_version`.

#### 7. Preflight snapshot: legacy `processor_run` was still in its original narrow shape

Current live schema and ORM confirm:

- table: `processor_run`
- columns:
  - `run_id`
  - `project_id`
  - `started_at`
  - `finished_at`
  - `engine`
  - `engine_version`
  - `docs_processed`
  - `tokens_total`
  - `lemmas_total`
  - `ngrams_total`
  - `status`
  - `note`
- status constraint still allows only:
  - `running`
  - `ok`
  - `failed`

This means the foundation patch must explicitly account for the status
constraint and for legacy-row compatibility during migration.

#### 8. Crash recovery must move into the foundation wave

`DBService.recover_from_crash()` currently only recovers:

- `ProcessorRun.status == 'running'`

If the new NLP run-state model introduces statuses such as staged, paused,
finalizing, or cancelled, crash recovery cannot wait until a later patch; it
must be updated in the same foundation wave as the schema/runtime change.

## Implemented foundation wave (2026-03-09)

### PATCH-NLP-00 status

Implemented:

- `docs/REFERENCE_PROJECT_GUIDE.md`
- `docs/NLP_PROCESS_CHECKPOINT_PLAN.md`
- task30/extract-terms docs updated to remove stale assumptions before coding

### PATCH-NLP-01 status

Implemented:

- `app/infra/migrations/037_nlp_run_state.sql`
- `app/infra/sa_models.py`
- `app/domain/dto.py`
- `app/services/process_service.py`
- `app/services/db_service.py`
- `tests/test_process_run_state_foundation.py`

Delivered in this wave:

- `processor_run` now includes:
  - `docs_total`
  - `docs_failed`
  - `chunks_total`
  - `chunks_completed`
  - `stage`
  - `last_doc_id`
  - `params_hash`
  - `error_message`
- `ProcessService.process_document()` now populates these fields for current
  single-document processing runs
- `reprocess_document()` keeps monkeypatch/backward-compatibility for tests and
  overridden `process_document()` implementations
- `DBService.recover_from_crash()` now also sets `stage='failed'` and
  `error_message` on recovered running rows

Validation:

- targeted regressions:
  - `29 passed in 80.68s`
  - artifact: `build/logs/nlp_prework/pytest_nlp_foundation.log`
- import smoke:
  - `OK 37 True`
  - artifact: `build/logs/nlp_prework/import_smoke_nlp_foundation.log`
- approved DB migration evidence:
  - artifact: `build/logs/nlp_prework/hewiki_apply_migrations_nlp_foundation.log`
  - approved DB now at `schema_version=37`
  - post-migration open check:
    - artifact: `build/logs/nlp_prework/db_open_self_check_nlp_foundation_post_migration.json`
    - `ok=true`, `elapsed_ms=12`
  - non-blocking operational note:
    - the migration log surfaced `Failed to unlock file: [Errno 13] Permission denied`
    - no stale `migrate.lock` remained afterward
    - post-migration DB open succeeded, so this is a known Windows lock-cleanup
      warning, not a blocking migration failure
- approved DB CLI dry-run after migration:
  - artifact: `build/logs/nlp_prework/process_reference_corpus_dry_run_post037.log`
  - script still reports `Current schema version: 37` and exits with
    `Nothing to process. Exiting.`
- approved DB live controlled probe:
  - artifact: `build/logs/nlp_prework/hewiki_live_nlp_foundation_probe.log`
  - temporary project + document processed successfully on the real DB
  - resulting `processor_run` row had:
    - `status='ok'`
    - `stage='completed'`
    - `docs_total=1`
    - `docs_processed=1`
    - `docs_failed=0`
    - `chunks_total=1`
    - `chunks_completed=1`
    - `last_doc_id=<live doc id>`
    - non-empty `params_hash`
  - cleanup succeeded and left no `BENCH_NLP_FOUNDATION_%` projects:
    - artifact: `build/logs/nlp_prework/hewiki_live_nlp_foundation_cleanup_check.log`

## Recommended patch series

### PATCH-NLP-00: docs and contract alignment

Status:

- implemented on 2026-03-09

Files:

- `docs/REFERENCE_PROJECT_GUIDE.md`
- `docs/NLP_PROCESS_CHECKPOINT_PLAN.md`
- task/plan docs as needed

Requirements:

- correct stale UI-vs-CLI processing assumptions
- record baseline evidence and approved-DB limitations
- keep the saved NLP plan synchronized with the real repo state before coding

### PATCH-NLP-01: durable processor run state and crash recovery compatibility

Status:

- implemented on 2026-03-09

Files:

- `app/infra/migrations/...`
- `app/infra/sa_models.py`
- `app/services/process_service.py`
- `app/domain/dto.py`
- `app/services/db_service.py`

Requirements:

- add staged/resumable run state for NLP processing
- migrate from the current legacy `processor_run` shape without losing old rows
- keep migration logic compatible with `schema_meta`
- include:
  - `status`
  - `stage`
  - `last_doc_id`
  - `docs_total`
  - `docs_processed`
  - `docs_failed`
  - `chunks_total`
  - `chunks_completed`
  - `params_hash`
  - `error_message`
- update crash recovery in the same patch so unfinished staged runs are not left
  in an impossible state after restart

### PATCH-NLP-02: structured service callbacks

Status:

- implemented on 2026-03-09

Files:

- `app/services/process_service.py`
- `scripts/process_reference_corpus.py`
- `tests/test_process_batch_run_state.py`
- `tests/test_reference_processing_guard.py`

Requirements:

- add `progress_callback` and `state_callback`
- preserve deterministic `doc_id ASC` ordering
- expose cooperative `cancel_check` / `pause_check`
- keep safe checkpoint boundaries at end-of-document or end-of-chunk only
- add deterministic CLI resume flow for the new run state, but keep reference
  processing CLI-only

Delivered in this wave:

- `ProcessService.process_documents_batch()` now creates or resumes a batch-level
  `processor_run` row instead of relying on transient loop counters only
- structured `NLPProcessRunState` payloads are emitted for:
  - `started`
  - `resumed`
  - `processing`
  - `chunk_complete`
  - `paused`
  - `cancelled`
  - `completed`
- the batch run contract is now gated by:
  - `params_hash`
  - `source_label`
  - `is_reprocess`
  - full deterministic `doc_id ASC` slice identity via `doc_ids_hash`
  - `doc_count`
  - `first_doc_id`
  - `last_doc_id`
- resume keeps the original chunk contract from the persisted batch note, even
  if the operator reruns the CLI with a different `--chunk-size`
- `scripts/process_reference_corpus.py` now supports `--resume-latest` and
  routes reference-scale processing through the batch run-state path
- CLI logging is now stage-aware and throttled by run/chunk state instead of
  emitting one free-form line per chunk loop iteration

Validation:

- targeted regressions:
  - `34 passed in 121.83s`
  - artifact: `build/logs/nlp_prework/pytest_nlp_patch02_final_candidate.log`
- approved DB live resume proof:
  - setup artifact:
    `build/logs/nlp_prework/hewiki_cli_patch02_resume_final_setup.log`
  - resume artifact:
    `build/logs/nlp_prework/hewiki_cli_patch02_resume_final_run.log`
  - postcheck/cleanup artifact:
    `build/logs/nlp_prework/hewiki_cli_patch02_resume_final_postcheck.log`
  - confirmed on `2026-03-09` against the approved
    `hewiki_gpu_processing test.db`:
    - initial controlled run created `run_id=387620`
      with `status='cancelled'`, `docs_processed=1`, `chunks_completed=1`
    - CLI `--resume-latest` reused the same `run_id=387620`
    - the resumed run preserved the original chunk contract:
      `chunks_total=2`, `chunks_completed=2`
      even though the CLI rerun used the default `--chunk-size 50`
    - cleanup removed all temporary `BENCH_NLP_CLI_%` projects afterward

### PATCH-NLP-03: regular-project progress UI

Status:

- pending

Files:

- `app/ui/workers.py`
- `app/ui/documents_view.py`
- `app/ui/dialogs/nlp_process_progress_dialog.py`

Requirements:

- add worker state signal
- add `pause/resume/cancel`
- mirror the staged extraction progress dialog contract
- keep all UI mutations on the main thread

### PATCH-NLP-04: CLI resume and verify contract

Status:

- pending

Files:

- `scripts/process_reference_corpus.py`
- `app/services/process_service.py`
- docs
- tests

Requirements:

- keep the implemented `--resume-latest` flow deterministic under explicit
  operator selection
- add `--resume-run-id` or equivalent explicit resume selection when multiple
  incomplete runs exist
- add `--verify-only` / contract-check mode for CLI preflight without writing
- refuse explicit resume when `params_hash` or stored source identity changed
- validate this behavior with temporary DB fixtures or controlled sandbox slices,
  not only against the already-processed approved DB

### PATCH-NLP-05: optional future staging/offline concept

Status:

- pending / only if product scope requires it

Only if product requirements later demand detached/offline NLP processing:

- introduce prepared manifest / staging DB contract
- define merge-back protocol explicitly
- keep this out of the first implementation wave

## Non-negotiable invariants

- reference corpora remain CLI-only for real NLP processing
- regular-project UI may get a premium progress dialog, but not at the cost of
  long write transactions
- resume must be deterministic and gated by run parameters
- cancel must leave the DB consistent and resumable
- no force-termination of NLP workers
- implementation proof for resume/cancel must use controlled fixtures because
  the approved DB is already fully processed

## Related follow-up for extract terms

When the NLP plan is implemented, the next convergence step for term extraction is:

- align run-state vocabulary and progress dialog semantics between NLP and terms
- then evaluate whether token/POS snapshots from NLP can replace sentence re-parse
  inside `TermExtractionService`
