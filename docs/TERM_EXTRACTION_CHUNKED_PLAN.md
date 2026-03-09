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
- current schema after migration `037_nlp_run_state`: `37`

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
- `build\logs\task30\pipeline_bench_report_20260309_092015.md`
- `build\logs\task30\pipeline_bench_report_20260309_104104.md`
- `build\logs\task30\pipeline_bench_report_20260309_173819.md`
- `build\logs\task30\pipeline_bench_report_20260309_175023.md`

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
- approved live ceiling evidence:
  - `extract_terms --reuse-working-db --pre-reset-sandbox --post-cleanup-bench --tier ceiling`
  - `pre_reset = 291.628 s`
  - `slice_clone = 440.776 s`
  - `extract_terms stage = 1281.056 s`
  - `post_cleanup_bench = 68.910 s`
  - `overall wall = 2085.892 s`
  - stage runtime stayed below the nominal `1800 s` ceiling budget
  - full one-command workflow exceeded the current overall wall budget by
    `285.892 s`, so this is the confirmed local machine ceiling for the full
    pre-reset workflow
- approved warm/reuse-base-copy ceiling evidence:
  - `extract_terms --reuse-base-copy --reuse-working-db --post-cleanup-bench --tier ceiling`
  - `base_copy = 0.000 s`
  - `slice_clone = 416.890 s`
  - `extract_terms stage = 1496.608 s`
  - `post_cleanup_bench = 82.140 s`
  - `overall wall = 1996.452 s`
  - warm reuse removes the cold reset cost, but full workflow still exceeds the
    current `1800 s` wall budget by `196.452 s`
  - this confirms that the practical contract split should be:
    - `stage wall`
    - `full workflow wall`
- approved prepared-fixture ceiling evidence:
  - fixture build:
    `prepare_bench_fixture --db-path J:\Project_Vibe\V_book\build\bench\hewiki_pipeline_ceiling_fixture.db --copy-target --source-db ...test.db --bench-project-name BENCH_PIPELINE_FIXTURE_CEILING --tier ceiling`
  - fixture-backed run:
    `extract_terms --reuse-working-db --reuse-bench-slice --pre-reset-sandbox --prepared-source-db J:\Project_Vibe\V_book\build\bench\hewiki_pipeline_ceiling_fixture.db --tier ceiling`
  - artifacts:
    - `build\logs\task30\pipeline_bench_report_20260309_130908.md`
    - `build\logs\task30\pipeline_bench_report_20260309_132149.md`
  - fixture build metrics:
    - `base_copy = 291.182 s`
    - `bench slice clone = 412.378 s`
    - `overall wall = 706.530 s`
  - fixture-backed ceiling metrics:
    - `base_copy/pre_reset = 285.941 s`
    - `slice_clone = 14.499 s`
    - `pre_stage_overhead = 302.903 s`
    - `extract_terms stage = 1275.001 s`
    - `overall wall = 1580.967 s`
  - this is the first completed full-workflow `ceiling` run on this machine
    that stays under the current `1800 s` wall budget
- approved fixture lifecycle hardening evidence:
  - fixture refresh:
    `refresh_bench_fixture --db-path J:\Project_Vibe\V_book\build\bench\hewiki_pipeline_ceiling_fixture.db --copy-target --source-db ...test.db --bench-project-name BENCH_PIPELINE_FIXTURE_CEILING --tier ceiling`
  - fixture verify:
    `verify_bench_fixture --db-path J:\Project_Vibe\V_book\build\bench\hewiki_pipeline_ceiling_fixture.db --copy-target --source-db ...test.db --bench-project-name BENCH_PIPELINE_FIXTURE_CEILING --tier ceiling`
  - artifacts:
    - `build\logs\task30\pipeline_bench_report_20260309_173819.md`
    - `build\logs\task30\pipeline_bench_report_20260309_175023.md`
  - refresh metrics:
    - `base_copy/refresh = 289.567 s`
    - `bench slice clone = 419.950 s`
    - `overall wall = 712.619 s`
  - verify metrics:
    - `fixture schema version = 36`
    - `source schema version = 36`
    - `verify stage wall = 1.464 s`
    - `overall wall = 2.249 s`
  - this hardens the prepared-fixture lifecycle into:
    - explicit refresh
    - explicit verify
    - fixture-backed heavy-tier run
- after the run, the sandbox contained `0` remaining `BENCH_%` projects and no
  SQLite sidecar files

Suggested benchmark tiers for repeatable task30 runs:

- `smoke`: `doc_limit=30`, wall budget `300 s`
- `medium`: `doc_limit=1000`, wall budget `600 s`
- `large`: `doc_limit=2000`, wall budget `900 s`
- `ceiling`: `doc_limit=6000`, wall budget `1800 s`

Recommended heavy-tier workflow:

- `smoke/medium/large` can continue to use the one-command maintenance cycle:
  - `extract_terms --reuse-working-db --pre-reset-sandbox --post-cleanup-bench --tier ...`
- `ceiling` should use a prepared fixture DB:
  - first verify the existing fixture:
    `verify_bench_fixture --db-path ...hewiki_pipeline_ceiling_fixture.db --copy-target --source-db ...test.db --bench-project-name BENCH_PIPELINE_FIXTURE_CEILING --tier ceiling`
  - if verify fails or the approved source contract changed, refresh the fixture:
    `refresh_bench_fixture --db-path ...hewiki_pipeline_ceiling_fixture.db --copy-target --source-db ...test.db --bench-project-name BENCH_PIPELINE_FIXTURE_CEILING --tier ceiling`
  - first-time bootstrap can still use:
    `prepare_bench_fixture --db-path ...hewiki_pipeline_ceiling_fixture.db --copy-target --source-db ...test.db --bench-project-name BENCH_PIPELINE_FIXTURE_CEILING --tier ceiling`
  - then run the reusable sandbox against that fixture:
    `extract_terms --reuse-working-db --reuse-bench-slice --pre-reset-sandbox --prepared-source-db ...hewiki_pipeline_ceiling_fixture.db --bench-project-name BENCH_PIPELINE_FIXTURE_CEILING --tier ceiling`
- do not combine `--reuse-bench-slice` with `--post-cleanup-bench`; the
  prepared `BENCH_*` project is intentionally preserved inside the fixture DB

Further implementation plan for extract terms:

- immediate runtime benchmarking work should stay focused on fixture lifecycle,
  reproducibility, and evidence quality rather than more stage-level
  `extract_terms` micro-optimization
- the next meaningful production-scale extract-terms change should be tied to
  the future NLP checkpoint plan:
  - align run-state vocabulary and progress UI semantics across NLP and terms
  - evaluate persisting token/POS snapshots during NLP processing to remove
    sentence re-parse from term extraction
- until that convergence work is funded, the current staged extractor is the
  accepted production path for overwrite mode on large projects

## Remaining follow-ups

### Follow-up A: NLP convergence and shared long-operation contract

- keep the current Terms staged progress flow stable; do not reopen blind
  progress-UI refactors before NLP catches up
- when checkpointed `process with NLP` lands, align:
  - run-state vocabulary
  - stage names
  - progress payload fields
  - pause/resume/cancel semantics
  - cooperative close behavior
- only then evaluate whether a shared reusable progress-dialog base is actually
  warranted across NLP and Terms

### Follow-up B: stronger fixture metadata only if evidence demands it

- the current fixture contract already verifies:
  - schema version
  - deterministic source slice
  - bench metadata
  - copied document count
- only add a richer manifest if later heavy tiers require stronger invariants
  than the current DB-contained metadata contract

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
