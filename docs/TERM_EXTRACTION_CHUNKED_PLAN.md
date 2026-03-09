# Chunked Term Extraction Plan

Date: 2026-03-09

## Problem

`extract_terms_for_project()` was previously a single large collect/finalize pass:

- re-parse all processed `document_sentence` rows in one logical run
- keep large in-memory counters before final writes
- restart from scratch after cancellation/failure

This was acceptable for small projects, but weak for large corpora and long-running
reference workflows.

## Implemented in this iteration

### 1. Staged run state

New schema:

- `term_extract_run`
- `term_extract_accumulator`

Purpose:

- persist run parameters and progress by document batches
- store staged aggregate counters before final write
- allow retry/resume after interrupted collect phase

### 2. Chunked collect phase

Overwrite mode now runs in two stages:

1. collect processed docs in deterministic `doc_id ASC` batches
2. upsert aggregate counters into `term_extract_accumulator`

Batch properties:

- bounded by `batch_size`
- committed after every batch
- resumable via `last_doc_id`
- safe to cancel before finalization

### 3. Atomic finalization

After staged collect completes:

- existing term tables are cleared
- staged counters are stored into `ngram` / `ngram_project_stat`
- clusters are built
- staged rows are deleted

Finalization is one transaction, so visible term tables are not partially overwritten
if this phase fails.

## Runtime contract

Current public API:

- `TermExtractionService.extract_terms_for_project(...)`

Current behavior:

- `overwrite=True` -> chunked staged pipeline
- `overwrite=False` -> legacy path retained for compatibility

Resume contract:

- latest matching staged run is resumed automatically
- if processed-doc count changed since the staged run was created, resume is refused
  and a fresh run is created instead

## Current UI behavior

- Terms extraction remains worker-threaded
- Terms confirmation dialog explicitly states that extraction is resumable
- Terms now opens a dedicated staged-progress dialog with:
  - doc progress bar
  - chunk counters
  - run id and last processed doc id
  - recent activity log
  - pause/resume/cancel controls
- inline Terms status text still receives stage messages from the chunked service
- if a staged run is cancelled, re-running extraction resumes it
- closing the Terms view requests cooperative extraction cancel instead of
  force-terminating the worker

## Bench evidence on approved DB

Target DB:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`
- initial Task 30 audit schema: `35`
- current schema after migration `036_term_extract_chunked`: `36`

Artifacts:

- `build\logs\pipeline_bench_report_20260309_021420.md`
- `build\logs\pipeline_bench_report_20260309_030439.md`
- `build\logs\task30\pipeline_bench_report_20260309_045419.md`
- `build\logs\task30\pipeline_bench_report_20260309_060810.md`
- `build\logs\task30\pipeline_bench_report_20260309_081444.md`
- `build\logs\task30\pipeline_bench_report_20260309_082025.md`
- `build\logs\task30\pipeline_bench_report_20260309_083133.md`
- `build\logs\task30\pipeline_bench_report_20260309_085005.md`
- `build\logs\task30\pipeline_bench_report_20260309_090248.md`

Observed `extract_terms` stage timings on the same DB/slice:

- pre-chunked staging patch, `doc_limit=30`: `13.960 s`
- post-chunked staging patch, `doc_limit=30`: `15.431 s`
- refreshed explicit-breakdown run, `doc_limit=1000`: `164.555 s`
- refreshed in-place sandbox run, `doc_limit=2000`: `318.852 s`

Observed harness overhead on the refreshed `doc_limit=1000` run:

- `working_copy = 295.783 s`
- `slice_clone = 91.022 s`
- `pre_stage_overhead = 388.572 s`
- `overall_wall = 554.462 s`

Observed harness overhead on the refreshed `doc_limit=2000` in-place run:

- `working_copy = 0.000 s`
- `slice_clone = 158.797 s`
- `pre_stage_overhead = 159.199 s`
- `overall_wall = 478.416 s`

Interpretation:

- small-slice runtime regressed slightly because run-state staging adds overhead
- the trade-off is intentional: resumability and bounded collect memory for large projects
- on this machine, repeated sandbox-copy overhead is large enough that the
  benchmark harness must record overhead separately from stage duration
- `--reuse-working-db` materially reduces wall-clock by removing the second
  giant sandbox copy for repeated runs
- a refreshed `doc_limit=6000` run still exceeded a `900 s` wall-clock budget
  even with both reuse modes enabled, so the older successful `257.680 s` stage
  artifact remains the best completed large-slice reference for `6000` docs

Sandbox maintenance follow-up:

- the reusable `2000/6000` benchmark sandbox needed explicit maintenance
  because a stale reusable `-wal` file had grown to `19.9 GB`
- `reset_sandbox` now refreshes the sandbox through a fresh-file replace flow
  and completed on the approved DB in `282.138 s`
- `cleanup_sandbox` now uses the existing project fast-delete service and
  removed a live `BENCH_MAINTENANCE_SMOKE` project in `0.174 s` stage time
- both maintenance scenarios now finish with `wal_checkpoint(TRUNCATE)` and
  leave no sidecar files behind the reusable sandbox DB

Maintenance-cycle follow-up:

- main benchmark scenarios now also support:
  - `--pre-reset-sandbox`
  - `--post-cleanup-bench`
- this turns reusable in-place benchmark runs into a single command instead of
  a manual `reset -> run -> cleanup` sequence
- approved live smoke evidence:
  - `extract_terms --reuse-working-db --pre-reset-sandbox --post-cleanup-bench --tier smoke`
  - `pre_reset = 290.549 s`
  - `extract_terms stage = 15.499 s`
  - `post_cleanup_bench = 0.951 s`
  - `overall wall = 314.838 s`
- approved live medium evidence:
  - `extract_terms --reuse-working-db --pre-reset-sandbox --post-cleanup-bench --tier medium`
  - `pre_reset = 290.648 s`
  - `slice_clone = 93.934 s`
  - `extract_terms stage = 172.700 s`
  - `post_cleanup_bench = 15.418 s`
  - `overall wall = 575.888 s`
  - this stayed within the current `medium` wall budget of `600 s`
- approved live large evidence:
  - `extract_terms --reuse-working-db --pre-reset-sandbox --post-cleanup-bench --tier large`
  - `pre_reset = 289.271 s`
  - `slice_clone = 170.809 s`
  - `extract_terms stage = 335.494 s`
  - `post_cleanup_bench = 27.753 s`
  - `overall wall = 826.349 s`
  - this stayed within the current `large` wall budget of `900 s`
- after the run, the sandbox contained `0` remaining `BENCH_%` projects and no
  SQLite sidecar files

Suggested benchmark tiers for repeatable task30 runs:

- `smoke`: `doc_limit=30`, wall budget `300 s`
- `medium`: `doc_limit=1000`, wall budget `600 s`
- `large`: `doc_limit=2000`, wall budget `900 s`
- `ceiling`: `doc_limit=6000`, wall budget `1800 s`

## Remaining follow-ups

### Follow-up A: richer extraction progress UI

- add cancel/resume controls in Terms UI
- show doc progress and finalization stage explicitly
- optional reuse of premium batch progress dialog with extraction-specific labels

### Follow-up B: bigger-slice benchmark refresh

- rerun `extract_terms` on a larger bounded slice after this patch
- record stage time separately from sandbox DB clone/bootstrap overhead

### Follow-up B2: optional benchmark sandbox housekeeping UX

- current CLI maintenance modes are sufficient for engineering use:
  - `reset_sandbox`
  - `cleanup_sandbox`
- only add an extra wrapper or preset if repeated operator use still proves noisy

### Follow-up C: deeper architecture tier if needed

If reference-scale runs are still too long:

- compute term candidates during NLP processing instead of re-parsing sentences later
- or persist token/POS sequence data needed for deterministic term extraction
- or materialize per-run / per-project helper tables for direct finalize paths

## Files touched in this wave

- `app/infra/migrations/036_term_extract_chunked.sql`
- `app/infra/sa_models.py`
- `app/domain/dto.py`
- `app/services/term_extraction_service.py`
- `app/ui/workers.py`
- `app/ui/terms_view.py`
- `tests/test_term_extraction_service_large_project.py`
