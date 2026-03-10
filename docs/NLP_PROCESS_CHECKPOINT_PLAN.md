# NLP Processing Checkpoint Plan

Date: 2026-03-09

## Purpose

This document saves the current implementation plan for bringing `process with NLP`
to the same engineering maturity level as staged `extract terms`, without losing
the confirmed repo context discovered during the Task 30 follow-up work.

Current approved DB state after the latest convergence wave:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`
- `schema_version=39` after migration `039_reprocess_fk_delete_indexes`

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

- implemented on 2026-03-09

Files:

- `app/ui/dialogs/nlp_process_progress_dialog.py`
- `app/ui/workers.py`
- `app/ui/documents_view.py`
- `tests/test_documents_process_progress_ui.py`
- `tests/test_task12_fts_nlp.py`
- `tests/test_process_batch_run_state.py`

Requirements:

- add worker state signal
- add `pause/resume/cancel`
- mirror the staged extraction progress dialog contract
- keep all UI mutations on the main thread

Delivered in this wave:

- `ProcessWorker` now routes both regular processing and re-processing through
  `ProcessService.process_documents_batch()` with:
  - structured `state_changed`
  - cooperative `cancel()/pause()/resume()`
  - `resume_latest=True`
  - `source_label='documents_ui'`
- `reprocess_document()` was extended so batch re-processing can reuse the same
  resumable run-state contract without creating extra per-document run rows
- added dedicated `NLPProcessProgressDialog` with:
  - stage label
  - run id
  - doc progress
  - chunk progress
  - last processed doc id
  - elapsed / last activity
  - bounded recent activity log
  - pause/resume/cancel controls
- `DocumentsView` now:
  - opens the new dialog for both `Process with NLP` and `Re-process`
  - updates inline progress/status from structured state
  - disables conflicting process/delete actions while the worker is active
  - requests cooperative cancellation on close instead of calling `terminate()`

Validation:

- targeted regressions:
  - `40 passed in 55.33s`
  - artifact: `build/logs/nlp_prework/pytest_nlp_patch03_ui_candidate.log`
- import smoke:
  - artifact: `build/logs/nlp_prework/import_smoke_nlp_patch03_ui.log`
  - result: `OK`
- approved DB live regular-project probe:
  - artifact: `build/logs/nlp_prework/hewiki_live_nlp_patch03_ui_probe.log`
  - confirmed on the approved `hewiki_gpu_processing test.db`:
    - temporary regular project was created on the live DB
    - `ProcessWorker` completed a batch `process` run with:
      - `run_id=387616`
      - `status='ok'`
      - `stage='completed'`
      - `docs_total=2`
      - `docs_processed=2`
    - the same temp project then completed a batch `reprocess` run with:
      - `run_id=387617`
      - `status='ok'`
      - `stage='completed'`
      - `docs_total=2`
      - `docs_processed=2`
      - persisted note `is_reprocess=true`
    - cleanup succeeded and left no `BENCH_NLP_UI_%` projects behind

### PATCH-NLP-04: CLI resume and verify contract

Status:

- implemented on 2026-03-09

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

Delivered in this wave:

- `ProcessService.verify_batch_run_contract()` now exposes a reusable
  service-level verifier for:
  - fresh batch contracts
  - `resume_latest`
  - explicit `resume_run_id`
- `process_documents_batch()` now supports `resume_run_id=` and refuses
  ambiguous `resume_latest + resume_run_id` combinations
- `scripts/process_reference_corpus.py` now supports:
  - `--resume-run-id <id>`
  - `--verify-only`
- CLI verify mode exits without writes and returns:
  - `0` when the contract is valid
  - `3` when the requested resume contract is invalid
- resumable auto-selection is now intentionally limited to:
  - `paused`
  - `cancelled`
  - `failed`
  and no longer treats `status='running'` rows as safe resume candidates

Validation:

- targeted regressions:
  - `47 passed in 199.98s`
  - artifact: `build/logs/nlp_prework/pytest_nlp_patch04_resume_verify.log`
- approved DB live explicit-resume proof:
  - setup artifact:
    `build/logs/nlp_prework/hewiki_cli_patch04_resume_verify_setup.log`
  - verify artifact:
    `build/logs/nlp_prework/hewiki_cli_patch04_resume_verify_verify.log`
  - resume artifact:
    `build/logs/nlp_prework/hewiki_cli_patch04_resume_verify_resume.log`
  - postcheck/cleanup artifact:
    `build/logs/nlp_prework/hewiki_cli_patch04_resume_verify_postcheck.log`
  - confirmed on the approved `hewiki_gpu_processing test.db`:
    - a controlled interrupted reference-style batch run was created on a
      temporary `BENCH_NLP_CLI_PATCH04_%` project
    - `--verify-only --resume-run-id <run_id>` succeeded without mutating the DB
    - `--resume-run-id <run_id>` resumed the exact selected run and finished it
    - cleanup removed all temporary `BENCH_NLP_CLI_PATCH04_%` projects

### PATCH-NLP-05: optional future staging/offline concept

Status:

- pending / only if product scope requires it

Only if product requirements later demand detached/offline NLP processing:

- introduce prepared manifest / staging DB contract
- define merge-back protocol explicitly
- keep this out of the first implementation wave

### PATCH-CONV-01: Terms/NLP state semantics alignment

Status:

- implemented on 2026-03-09

Files:

- `app/domain/dto.py`
- `app/services/term_extraction_service.py`
- `app/ui/dialogs/term_extraction_progress_dialog.py`
- `app/ui/terms_view.py`
- tests
- docs

Delivered in this wave:

- staged term extraction now emits structured state with NLP-aligned core
  fields:
  - `project_id`
  - `status`
  - `stage`
  - `docs_total`
  - `docs_processed`
  - `docs_failed`
  - `chunks_total`
  - `chunks_completed`
  - `last_doc_id`
  - `error_message`
- term extraction now emits explicit `paused` and `resumed` phases at the
  batch checkpoint
- finalize-stage terms payloads no longer leak empty `phase` values
- Terms progress dialog now relies on structured state for recent activity,
  reducing semantic drift from the NLP progress dialog

Validation:

- targeted convergence regressions:
  - `46 passed in 205.80s`
  - artifact: `build/logs/nlp_prework/pytest_nlp_terms_convergence.log`
- approved DB live convergence probe:
  - artifact: `build/logs/nlp_prework/hewiki_live_terms_convergence_probe.log`
  - confirmed:
    - real approved DB run emitted both `paused` and `resumed`
    - no empty `phase` remained in the state stream
    - final completed term-extraction state carried the aligned metadata fields

### PATCH-CONV-02: shared staged progress dialog foundation

Status:

- implemented on 2026-03-09

Files:

- `app/ui/dialogs/staged_operation_progress_dialog.py`
- `app/ui/dialogs/nlp_process_progress_dialog.py`
- `app/ui/dialogs/term_extraction_progress_dialog.py`
- `tests/test_staged_operation_progress_dialogs.py`
- docs

Delivered in this wave:

- NLP and Terms now share one staged-progress dialog foundation for:
  - common layout
  - structured state rendering
  - bounded activity log
  - heartbeat / elapsed / idle labels
  - pause/resume/cancel button lifecycle
  - cooperative close behavior
- operation-specific wording remains local to each dialog class, so user-visible
  text stays stable while the duplicated implementation is removed
- direct Qt dialog regressions now cover the real dialog classes instead of
  relying only on `DocumentsView` / `TermsView` wiring tests

Validation:

- targeted dialog/shared-base regressions:
  - `28 passed in 93.79s`
  - artifact: `build/logs/nlp_prework/pytest_nlp_terms_shared_dialog.log`
- import smoke:
  - artifact: `build/logs/nlp_prework/import_smoke_terms_nlp_shared_dialog.log`
  - result: `OK`
- approved DB app-open smoke:
  - artifact:
    `build/logs/nlp_prework/db_open_self_check_terms_nlp_shared_dialog.json`
  - confirmed `db_open ok` on the approved `hewiki_gpu_processing test.db`

### PATCH-CONV-03: sentence NLP snapshots for term-extraction reuse

Status:

- implemented on 2026-03-09

Files:

- `app/infra/migrations/038_sentence_nlp_snapshot.sql`
- `app/infra/nlp_snapshot_codec.py`
- `app/infra/sa_models.py`
- `app/services/process_service.py`
- `app/services/term_extraction_service.py`
- `tests/test_sentence_nlp_snapshot_reuse.py`
- docs

Delivered in this wave:

- `ProcessService.process_document()` now persists sentence-level NLP snapshots
  alongside `document_sentence` rows using a dedicated
  `sentence_nlp_snapshot` table
- the snapshot payload stores token/POS/lemma data plus a
  `sentence_text_hash`, letting later consumers verify that the sentence text
  still matches the stored NLP output
- `TermExtractionService` now prefers persisted snapshots before reparsing
  sentence text through the current engine; fallback reparse remains in place
  for missing, stale, or malformed snapshot rows
- this makes the first production data-path convergence between `process with
  NLP` and `extract terms` real, not just planned

Validation:

- targeted snapshot/reuse regressions:
  - `48 passed in 209.93s`
  - artifact: `build/logs/nlp_prework/pytest_sentence_snapshot_reuse.log`
- import smoke:
  - artifact: `build/logs/nlp_prework/import_smoke_sentence_snapshot_reuse.log`
  - result: `OK`
- prebuild/package smoke:
  - artifact:
    `build/logs/nlp_prework/prebuild_validate_sentence_snapshot_reuse.log`
  - result: all checks passed
- approved DB open smoke:
  - artifact:
    `build/logs/nlp_prework/db_open_self_check_sentence_snapshot_approved.json`
  - confirmed `db_open ok` on the approved DB
- approved DB live snapshot-reuse probe:
  - artifact:
    `build/logs/nlp_prework/hewiki_live_sentence_snapshot_probe_v2.log`
  - confirmed on the approved DB:
    - current schema advanced to `38`
    - a temporary project produced `2` persisted sentence snapshots during NLP
      processing
    - term extraction completed successfully even when its engine was replaced
      with a failing stub, proving snapshot reuse instead of forced reparse
    - cleanup removed the temporary project cleanly

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

The first convergence step for term extraction is now implemented:

- keep the shared staged dialog contract stable across NLP and terms
- keep the current `prefer snapshot / fallback reparse` contract stable
- only expand this with snapshot backfill, freshness/version gating, or broader
  coverage reporting if evidence from legacy processed projects shows too much
  fallback reparsing

## Snapshot coverage audit (2026-03-10)

Migration truth re-checked on both real hewiki DBs:

- main install DB:
  `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db`
  - pre-check: `schema_version=35`
  - post-check: `schema_version=38`
- dev/test DB:
  `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`
  - pre-check: `schema_version=38`
  - post-check: `schema_version=38`

Artifacts:

- `build/logs/nlp_coverage/db_migration_probe.log`
- `build/logs/nlp_coverage/db_open_main_install.json`
- `build/logs/nlp_coverage/db_open_dev_test.json`
- `build/logs/nlp_coverage/sentence_snapshot_coverage_probe_after_cleanup.jsonl`
- `build/logs/nlp_coverage/orphan_doc_hierarchy_probe.jsonl`

Coverage findings on project-attached processed docs:

- main install DB:
  - project `Hebrew Wikipedia Baseline`
  - `387639` processed docs
  - `13387860` sentences
  - `0` sentence snapshot rows
  - sentence coverage `0.0%`
  - full-doc coverage `0.0%`
- dev/test DB:
  - all visible processed projects also sit at `0.0%` snapshot coverage
  - after orphan cleanup, total live `sentence_nlp_snapshot` rows returned to `0`

Additional note:

- both DBs contain `2` pre-existing processed `source_document` rows whose
  `corpus_id` no longer resolves to a live `source_corpus`
- this is a broader data-quality issue, not a new snapshot-specific regression,
  so project-attached coverage numbers above are the trustworthy basis for the
  backfill decision

Decision after audit:

- a dedicated snapshot backfill patch is justified
- a freshness/version-gating patch is not the next priority, because the real
  blocker is absence of snapshots on legacy processed corpora, not mismatch of
  existing snapshots

## PATCH-NLP-BF-01 implemented (2026-03-10)

Files:

- `app/services/process_service.py`
- `scripts/process_reference_corpus.py`
- `tests/test_sentence_snapshot_backfill_batch.py`
- `tests/test_process_reference_cli_verify.py`
- `docs/NLP_PROCESS_CHECKPOINT_PLAN.md`
- `docs/REFERENCE_PROJECT_GUIDE.md`
- `docs/TERM_EXTRACTION_CHUNKED_PLAN.md`
- `docs/TASK30_IMPLEMENTATION_PLAN_2026-03-09.md`

Delivered:

- new CLI mode `--backfill-snapshots` for already processed project documents
  that still lack `sentence_nlp_snapshot` rows
- new read-only audit mode `--coverage-only`
- backfill reuses the current DB-backed batch `processor_run` contract instead
  of introducing a second run-ledger model
- deterministic resume contract stays based on the full processed-doc slice,
  not the shrinking "still missing" subset, so interrupted runs remain
  resumable even after some docs become covered
- backfill writes only missing `sentence_nlp_snapshot` rows
- backfill does not change document NLP status, lemma tables, or term tables
- the same `--resume-latest`, `--resume-run-id`, and `--verify-only`
  mechanisms now also work for snapshot-backfill runs through the explicit
  `snapshot_backfill_v1` contract

Validation:

- targeted backfill + CLI regressions:
  - `29 passed in 158.98s`
  - artifact: `build/logs/nlp_backfill/pytest_snapshot_backfill.log`
- import smoke:
  - artifact: `build/logs/nlp_backfill/import_smoke_snapshot_backfill.log`
  - result: `OK`
- live approved dev/test DB probe:
  - coverage-only artifact:
    `build/logs/nlp_backfill/live_cli_probe_coverage.log`
  - backfill artifact:
    `build/logs/nlp_backfill/live_cli_probe_backfill.log`
  - post-check artifact:
    `build/logs/nlp_backfill/live_cli_probe_postcheck.log`
  - confirmed on
    `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`:
    - temporary processed docs started at `0.0%` snapshot coverage
    - backfill created `4` sentence snapshots for `2` docs
    - cleanup removed the temporary project and left no leftovers

Current next step after implementation:

- do not add freshness/version gating yet
- first measure how much legacy coverage improves after operators actually run
  backfill on long-lived processed projects
- if fallback reparsing remains significant after backfill adoption, only then
  evaluate:
  - freshness/version gates
  - backfill reporting/export wrappers
  - broader snapshot integrity checks

## Re-process hang fix and coverage decision (2026-03-10)

Files:

- `app/services/process_service.py`
- `app/ui/documents_view.py`
- `app/ui/dialogs/staged_operation_progress_dialog.py`
- `app/infra/migrations/039_reprocess_fk_delete_indexes.sql`
- `tests/test_process_service_remove_document_stats.py`
- `tests/test_documents_process_progress_ui.py`
- `tests/test_staged_operation_progress_dialogs.py`
- `tests/test_perf_indexes_present.py`

Delivered:

- fixed a live `re-process` stall observed on project `ID=5` in the approved
  dev/test DB after the staged dialog showed only `Created NLP batch run`
- the real hot path was the old project-wide orphan-lemma cleanup during
  `remove_document_stats()`, not the structured batch run contract itself
- re-process now cleans orphan lemmas only for the lemma ids touched by the
  current document, instead of sweeping the whole project
- migration `039_reprocess_fk_delete_indexes` adds the missing `lemma_id`
  cascade-supporting indexes on large child tables
- the regular-project NLP dialog now appends per-document progress activity
  immediately, so operators no longer wait on a frozen-looking
  `Created NLP batch run` line
- pressing `Cancel` now appends an explicit pending-cancel activity line; the
  effective cancellation point remains the next safe document boundary

Validation on the approved dev/test DB:

- DB:
  - `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`
- project:
  - `ID=5`
  - `Name=тест 9 марта`
  - `2` processed docs
- artifacts:
  - `build/logs/nlp_reprocess_project5/reprocess_project5_batch_postfix.jsonl`
  - `build/logs/nlp_reprocess_project5/reprocess_project5_postcheck.json`
  - `build/logs/nlp_reprocess_project5/reprocess_project5_worker_cancel.json`
- confirmed:
  - `remove_document_stats()` for the first doc completed in `0.711 s`
    instead of stalling for minutes
  - resumed live batch run `387617` finished both docs in about `16.5 s`
  - worker-path cancel stopped at the next document checkpoint and persisted
    a fresh run as `cancelled`

Coverage-only decision after the fix:

- `ID=5` (`тест 9 марта`):
  - already at `100.0%` sentence snapshot coverage after the re-process runs
- `ID=6` (`Mishneh Torah`):
  - `0.0%` coverage on `1` processed doc
  - useful only as a small smoke backfill target
- `ID=1` (`Hebrew Wikipedia Baseline`):
  - `0.0%` coverage on `387639` processed docs
  - this is the real decision-driving legacy target for snapshot backfill

Operational recommendation:

- do not use small projects such as `ID=5` to judge whether
  freshness/version hardening is needed; they are too small and `ID=5` is
  already fully covered
- `ID=6` can be used as a quick smoke backfill run
- use `ID=1` for the actual post-backfill coverage measurement that will decide
  whether any freshness/version hardening work is justified
