# Task 30 Implementation Plan (2026-03-09)

## Scope

This plan is based on the approved Task 30 audit executed against:

- DB path: `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`
- Verified runtime contract: `python -m app.main --db-path "<path above>"`
- Verified schema version on target DB at initial Task 30 audit: `35`
- Current schema version on the same DB after migration `039_reprocess_fk_delete_indexes`: `39`

This document records the implementation order for the confirmed findings only.
It is intentionally patch-oriented and conservative.

## Confirmed constraints

- Target app: PyQt6 desktop application with SQLite WAL.
- Heavy reference-scale DB:
  - `source_document`: ~387k rows
  - `document_sentence`: ~13.3M rows
  - `lemma`: ~2.07M rows
  - `lemma_doc_stat`: ~104.1M rows
- Long operations must remain worker-safe and UI-thread safe.
- Changes must preserve WAL-safe transaction behavior and keep diffs minimal.

## Confirmed findings driving implementation

### 1. Translation overlay workers are not fully hardened

- `TranslationResolveWorker` currently opens a write session even though it performs read-only overlay work.
- `TermsView` auto-translation flow does not have Dictionary-style anti-stale sequencing.
- `TranslateTextDialog` still uses forceful thread shutdown (`terminate()`) on cancel/close.

### 2. Instrumentation has drifted from live service paths

- `scripts/query_plan_audit.py` no longer reflects the real document picker service path.
- Some older perf docs are stale compared to current code.

### 3. Large-scale bottleneck is term extraction read/materialization pressure

- The confirmed live `TermExtractionService` path re-parses processed sentences and
  previously materialized full processed-document and sentence ORM collections.
- Bigram association scoring also repeated lemma-frequency lookups inside the
  n-gram store loop.
- `collect_queryplan_evidence.py` still captures a heavy diagnostic
  `lemma_doc_stat` rollup, but that query is not the live caller for the current
  extraction path.

### 4. Runtime readiness is inconsistent across feature families

- MT health and audio health use different readiness semantics.
- Runtime data/log roots resolve outside the repo workspace.
- Resource registry reports niqqud resources missing while bootstrap health still reports real inference readiness.

## Patch series

### PATCH-01: Worker safety hardening for translation overlays and ad-hoc translation

Status: implemented on 2026-03-09

Files:

- `app/ui/workers.py`
- `app/ui/terms_view.py`
- `app/ui/translate_text_dialog.py`
- `tests/test_terms_worker_lifecycle.py`
- `tests/test_translation_worker_read_session.py`
- `tests/test_translate_text_dialog_lifecycle.py`

Goals:

- Route read-only translation overlay work through `get_read_session()`.
- Add anti-stale sequencing to `TermsView` translation overlays.
- Replace ad-hoc translation `terminate()` flow with cooperative cancel handling.
- Ensure stale/retired worker completions do not mutate visible UI state.

Expected effect:

- Lower write-lock pressure from passive overlay reads.
- Eliminate stale overlay flashes in Terms after rapid paging/filtering.
- Remove unsafe thread termination from ad-hoc translation dialog flow.

Validation:

- Targeted pytest slice for worker lifecycle and dialog lifecycle.
- Existing translation and anti-stale regressions must still pass.
- Result: implemented and validated by
  `tests/test_terms_worker_lifecycle.py`,
  `tests/test_translation_worker_read_session.py`,
  `tests/test_translate_text_dialog_lifecycle.py`.

### PATCH-02: Diagnostic/perf evidence alignment

Status: implemented on 2026-03-09

Files:

- `scripts/query_plan_audit.py`
- `scripts/collect_queryplan_evidence.py`
- `docs/PERF_HARNESS.md`
- `docs/PERFORMANCE_SLO.md`

Goals:

- Align diagnostic scripts with current service-layer queries.
- Record target DB schema version and path in perf artifacts.
- Keep before/after perf comparisons reproducible on the approved DB.

Expected effect:

- Remove false bottlenecks caused by stale benchmark SQL.
- Preserve trustworthy perf evidence for future optimization patches.

Validation:

- Re-run perf harness and query-plan collection on the approved DB.
- Compare new artifacts under `build/logs/`.
- Result: implemented; refreshed artifacts include schema-aware outputs and
  live-service query-plan capture under `build/logs/task30/`.

### PATCH-03: Large-project collect/store mitigation

Status: implemented on 2026-03-09

Files:

- `app/services/term_extraction_service.py`
- `tests/test_term_extraction_service_large_project.py`

Goals:

- Keep overwrite rollback-safe by deferring destructive clears until the read
  phase succeeds.
- Stop materializing full processed-document and sentence ORM collections during
  extraction.
- Collapse repeated per-row lemma frequency lookups into one bounded prefetch for
  bigram scoring.

Current note:

- This patch does not yet rewrite `_cluster_terms()` into a streaming path and
  does not introduce new schema objects or migrations.
- Materialized helper tables remain a separate follow-up only if real extraction
  evidence still demands it after the bounded collect/store cleanup.

Expected effect:

- Lower peak memory pressure during extraction on reference-scale projects.
- Fewer repeated DB round-trips while storing scored bigrams.
- Safer overwrite semantics if read/parse fails mid-run.

Validation:

- New targeted tests for deferred overwrite ordering and a minimal
  end-to-end extraction pipeline.
- Non-destructive helper/collect probes on the approved DB.
- Result: implemented; extraction now collects first, clears second, then stores
  in one bounded write phase using lazy document/sentence iteration.

### PATCH-04: Readiness and health semantics cleanup

Status: implemented on 2026-03-09

Files:

- `app/services/health_check_service.py`
- related settings/provider tests

Goals:

- Unify readiness semantics for MT and audio providers.
- Make configured vs enabled vs optional reporting consistent.
- Document known runtime-root/resource-root assumptions.
- Treat explicit `pronunciation/phonikud/model_path` or `PHONIKUD_MODEL_PATH`
  as a valid installed niqqud resource source, even when the model lives
  outside the managed `data_root`.

Validation:

- Self-check JSON comparisons.
- Targeted provider config tests.
- Result: implemented; MT health now respects master enable + per-provider
  enable + chain membership semantics, matching audio-style readiness reporting.
- Result: implemented; resource registry now recognizes explicit external
  Phonikud model paths, so health/wizard state matches real inference readiness.
- Result: implemented; sentence-niqqud bootstrap now reports the post-generation
  `generator_mode` and persists the effective `phonikud_version` after real
  inference, not the stale pre-generation fallback mode.

### PATCH-05: Large-project clustering streaming

Status: implemented on 2026-03-09

Files:

- `app/services/term_extraction_service.py`
- `tests/test_term_extraction_service_large_project.py`

Goals:

- Remove full-project `.all()` materialization from `_cluster_terms()`.
- Keep clustering deterministic by batching on `he_canonical`.
- Backfill missing `he_canonical` values for legacy rows before batched reads.
- Preserve correct member metadata while clustering mixed `ngram` / `np` inputs.

Expected effect:

- Lower peak memory pressure during cluster creation on large projects.
- Safer clustering on projects that contain both legacy rows and new extraction output.
- Correct `source_kinds` and `member_doc_freq` persistence in cluster rows.

Validation:

- New targeted clustering regression in
  `tests/test_term_extraction_service_large_project.py`.
- Read-only batch probe on the approved hewiki DB confirmed deterministic
  canonical-key paging without destructive writes.
- Result: implemented; `_cluster_terms()` now clusters in canonical-key batches
  and no longer builds an in-memory map for the full project.

### PATCH-06: Chunked term extraction staging and resumable runs

Status: implemented on 2026-03-09

Files:

- `app/infra/migrations/036_term_extract_chunked.sql`
- `app/infra/sa_models.py`
- `app/domain/dto.py`
- `app/services/term_extraction_service.py`
- `tests/test_term_extraction_service_large_project.py`

Goals:

- Make `extract_terms_for_project()` process large projects in bounded doc batches
  instead of one monolithic collect pass.
- Persist staged aggregate counters so interrupted runs can resume instead of
  restarting from doc `1`.
- Keep overwrite-safe behavior by delaying final term-table mutation until the
  staged collect pass completes successfully.

Design:

- New `term_extract_run` table stores project/parameter/status/checkpoint state.
- New `term_extract_accumulator` table stores aggregated `(source_kind, n, surface)`
  counters with `freq_abs/doc_freq`.
- Public overwrite path now stages by doc batch, then performs one atomic finalization
  transaction into `ngram/ngram_project_stat/term_cluster`.
- Legacy non-overwrite path stays on the previous implementation to avoid widening
  behavioral surface unnecessarily.

Expected effect:

- Bounded RAM use during collect phase on large projects.
- Resume/retry support after cancellation/failure without losing staged work.
- No partial visible overwrite if collect fails before finalization starts.

Validation:

- New regression in `tests/test_term_extraction_service_large_project.py` covers
  cancel-after-first-batch and resume-to-success on the same staged run.
- Existing bounded extraction and clustering regressions still pass.
- Migration compatibility must be re-verified on the approved `hewiki_gpu_processing test.db`.

### PATCH-07: Term extraction UI/worker progress integration

Status: implemented on 2026-03-09

Files:

- `app/ui/workers.py`
- `app/ui/terms_view.py`
- `app/ui/dialogs/term_extraction_progress_dialog.py`
- `tests/test_terms_extract_progress_ui.py`

Goals:

- Surface chunked doc progress, resumable-run status, and finalization stage in UI.
- Add cooperative cancel/resume controls wired to the staged collect phase.
- Keep Terms view responsive without relying on an indeterminate progress bar only.

Result:

- Terms extraction now opens a dedicated staged-progress dialog with doc progress,
  chunk counters, run id, last processed doc id, recent activity log, and
  pause/resume/cancel controls.
- `ProjectTermExtractionWorker` now emits structured extraction state in addition
  to human-readable activity messages.
- `TermsView.closeEvent()` no longer force-terminates extraction threads; it
  requests cooperative cancel and lets the worker finish safely after the current
  checkpoint if needed.

### PATCH-08: Pipeline benchmark refresh for chunked extraction

Status: implemented on 2026-03-09

Files:

- `scripts/benchmarks/bench_reference_pipeline.py`
- `tests/test_pipeline_bench_runner_safety.py`
- `tests/test_pipeline_bench_argparse.py`
- `build/logs/task30/pipeline_bench_*`
- task docs as needed

Goals:

- Refresh apples-to-apples `extract_terms` benchmarks after chunked staging lands.
- Separate stage time from harness copy/bootstrap overhead in recorded evidence.

Result:

- Benchmark harness now records explicit timing breakdown for:
  - base sandbox copy
  - working DB copy
  - DB initialize
  - bench slice clone
  - pre-stage overhead total
  - stage wall total
  - overall wall total
- New `--reuse-base-copy` mode allows repeated runs against an existing local
  sandbox base DB without re-copying the source DB first.
- New `--reuse-working-db` mode allows repeated runs directly against an
  existing disposable sandbox DB at `--db-path`, skipping the temp working-copy
  clone entirely.
- New `--tier` presets make repeated task30 runs reproducible without manually
  remembering slice sizes and recommended wall-clock budgets.

Known evidence:

- On `2026-03-09`, bounded sandbox benchmark against
  `hewiki_gpu_processing test.db` produced:
  - `doc_limit=30`: `extract_terms = 13.960 s`
  - `doc_limit=6000`: `extract_terms = 257.680 s`
- On `2026-03-09`, refreshed harness evidence with explicit timing breakdown
  produced:
  - `doc_limit=1000`, `reuse_base_copy=true`
  - `working_copy = 295.783 s`
  - `slice_clone = 91.022 s`
  - `pre_stage_overhead = 388.572 s`
  - `extract_terms stage = 164.555 s`
  - `overall wall = 554.462 s`
- On `2026-03-09`, refreshed in-place sandbox evidence produced:
  - `doc_limit=2000`, `reuse_base_copy=true`, `reuse_working_db=true`
  - `working_copy = 0.000 s`
  - `slice_clone = 158.797 s`
  - `pre_stage_overhead = 159.199 s`
  - `extract_terms stage = 318.852 s`
  - `overall wall = 478.416 s`
- These figures already confirm the live cost scales with the extraction stage,
  but also that local sandbox-copy overhead is substantial on this machine.
- Attempted refreshed `doc_limit=6000` runs still exceeded a `900 s`
  wall-clock budget on this machine even after enabling both
  `reuse_base_copy=true` and `reuse_working_db=true`, so the older successful
  `257.680 s` stage artifact remains the best completed large-slice reference
  for `6000` docs.

Recommended task30 benchmark tiers:

- `smoke`: `doc_limit=30`, recommended wall budget `300 s`
- `medium`: `doc_limit=1000`, recommended wall budget `600 s`
- `large`: `doc_limit=2000`, recommended wall budget `900 s`
- `ceiling`: `doc_limit=6000`, recommended wall budget `1800 s`

### PATCH-09: Benchmark sandbox maintenance modes

Status: implemented on 2026-03-09

Files:

- `scripts/benchmarks/bench_reference_pipeline.py`
- `tests/test_pipeline_bench_runner_safety.py`
- `tests/test_pipeline_bench_argparse.py`
- `build/logs/task30/pipeline_bench_report_20260309_081444.md`
- `build/logs/task30/pipeline_bench_report_20260309_082025.md`

Goals:

- Make repeated task30 sandbox runs recoverable after huge reusable-WAL growth.
- Provide explicit `reset` and `cleanup` maintenance commands instead of ad-hoc
  manual DB surgery.
- Keep reusable sandbox DBs checkpointed so follow-up queries and runs do not
  stall behind large stale `-wal` files.

Result:

- Added `cleanup_sandbox` scenario to delete `BENCH_*` projects from a sandbox
  DB using the existing `ProjectService.delete_project()` fast path instead of a
  naive `dict_project` delete under `foreign_keys=ON`.
- Added `reset_sandbox` scenario to rebuild the sandbox DB from the approved
  source DB through a fresh temp file + replace flow, explicitly discarding old
  `-wal/-shm/-journal` sidecars.
- Added post-run SQLite maintenance for reusable sandbox DBs:
  `PRAGMA wal_checkpoint(TRUNCATE)` now runs after maintenance scenarios and
  after reusable in-place benchmark runs.
- Added unit coverage for parser contracts, cleanup routing, and stale-sidecar
  replacement behavior.

Observed evidence:

- Before this patch, `build\bench\hewiki_pipeline_task30_patch08_6000.db-wal`
  had grown to `19,941,055,472` bytes and even trivial `dict_project` reads on
  that sandbox stalled.
- `reset_sandbox` on the same DB completed successfully in `282.138 s` and
  removed all sidecars:
  - artifact: `build\logs\task30\pipeline_bench_report_20260309_081444.md`
- After reset, a live empty benchmark project
  `BENCH_MAINTENANCE_SMOKE` was inserted and then removed through
  `cleanup_sandbox` in `0.174 s` stage time / `0.957 s` overall wall:
  - artifact: `build\logs\task30\pipeline_bench_report_20260309_082025.md`
- Post-run maintenance on both scenarios reported `checkpoint=[0, 0, 0]` and
  left no `-wal/-shm/-journal` files alongside the sandbox DB.

### PATCH-10: One-command benchmark maintenance cycle

Status: implemented on 2026-03-09

Files:

- `scripts/benchmarks/bench_reference_pipeline.py`
- `tests/test_pipeline_bench_runner_safety.py`
- `tests/test_pipeline_bench_argparse.py`
- `build/logs/task30/pipeline_bench_report_20260309_083133.md`
- `build/logs/task30/pipeline_bench_report_20260309_085005.md`
- `build/logs/task30/pipeline_bench_report_20260309_090248.md`
- `build/logs/task30/pipeline_bench_report_20260309_092015.md`
- `build/logs/task30/pipeline_bench_report_20260309_104104.md`

Goals:

- Eliminate manual `reset -> run -> cleanup` operator sequencing for repeatable
  task30 tier runs.
- Keep reusable in-place sandbox runs clean after each benchmark by deleting the
  temporary bench project automatically.
- Preserve timing evidence so reset/cleanup overhead stays separated from stage
  runtime.

Result:

- Added `--pre-reset-sandbox` to force a fresh reusable sandbox refresh before a
  benchmark run.
- Added `--post-cleanup-bench` to delete the exact bench project after a
  successful run via the existing fast project-delete path.
- Added maintenance-cycle reporting to benchmark markdown/json artifacts:
  - pre-reset action
  - post-cleanup action
  - independent post-run SQLite checkpoint/truncate
- Added safety validation:
  - both flags require `--reuse-working-db`
  - post-cleanup also requires bench project names to stay under the `BENCH_`
    prefix contract

Observed evidence:

- Live smoke cycle on the approved sandbox DB completed successfully:
  - command shape:
    `extract_terms --reuse-working-db --pre-reset-sandbox --post-cleanup-bench --tier smoke`
  - artifact: `build\logs\task30\pipeline_bench_report_20260309_083133.md`
- Measured on `2026-03-09`:
  - `base_copy/pre_reset = 290.549 s`
  - `db_initialize = 1.716 s`
  - `slice_clone = 4.771 s`
  - `extract_terms stage = 15.499 s`
  - `post_cleanup_bench = 0.951 s`
  - `overall wall = 314.838 s`
- Live medium cycle on the same approved sandbox DB also completed successfully:
  - command shape:
    `extract_terms --reuse-working-db --pre-reset-sandbox --post-cleanup-bench --tier medium`
  - artifact: `build\logs\task30\pipeline_bench_report_20260309_085005.md`
  - `base_copy/pre_reset = 290.648 s`
  - `slice_clone = 93.934 s`
  - `extract_terms stage = 172.700 s`
  - `post_cleanup_bench = 15.418 s`
  - `overall wall = 575.888 s`
  - this stayed within the current `medium` tier wall budget of `600 s`
- Live large cycle on the same approved sandbox DB also completed successfully:
  - command shape:
    `extract_terms --reuse-working-db --pre-reset-sandbox --post-cleanup-bench --tier large`
  - artifact: `build\logs\task30\pipeline_bench_report_20260309_090248.md`
  - `base_copy/pre_reset = 289.271 s`
  - `slice_clone = 170.809 s`
  - `extract_terms stage = 335.494 s`
  - `post_cleanup_bench = 27.753 s`
  - `overall wall = 826.349 s`
  - this stayed within the current `large` tier wall budget of `900 s`
- Live ceiling cycle on the same approved sandbox DB completed functionally but
  exceeded the current overall wall budget:
  - command shape:
    `extract_terms --reuse-working-db --pre-reset-sandbox --post-cleanup-bench --tier ceiling`
  - artifact: `build\logs\task30\pipeline_bench_report_20260309_092015.md`
  - `base_copy/pre_reset = 291.628 s`
  - `slice_clone = 440.776 s`
  - `extract_terms stage = 1281.056 s`
  - `post_cleanup_bench = 68.910 s`
  - `overall wall = 2085.892 s`
  - interpretation:
    - stage runtime itself stayed below `1800 s`
    - full one-command ceiling workflow exceeded the current `ceiling` wall
      budget by `285.892 s`, so this is the confirmed machine ceiling for the
      current local workflow contract
- Correct warm/reuse-base-copy ceiling cycle also completed functionally but
  still exceeded the current overall wall budget:
  - command shape:
    `extract_terms --reuse-base-copy --reuse-working-db --post-cleanup-bench --tier ceiling`
  - artifact: `build\logs\task30\pipeline_bench_report_20260309_104104.md`
  - `base_copy = 0.000 s`
  - `slice_clone = 416.890 s`
  - `extract_terms stage = 1496.608 s`
  - `post_cleanup_bench = 82.140 s`
  - `overall wall = 1996.452 s`
  - interpretation:
    - warm reuse removes the cold reset cost, but full workflow still exceeds
      the current `ceiling` wall budget by `196.452 s`
    - this confirms the actionable split: `stage wall` can pass while `full
      workflow wall` still fails on this machine
- After the run:
  - `dict_project where name like 'BENCH_%'` returned `0`
  - no `-wal/-shm/-journal` files remained next to the sandbox DB

### PATCH-11: Prepared fixture workflow for heavy benchmark tiers

Status: implemented on 2026-03-09

Files:

- `scripts/benchmarks/bench_reference_pipeline.py`
- `tests/test_pipeline_bench_runner_safety.py`
- `tests/test_pipeline_bench_argparse.py`
- `build/logs/task30/pipeline_bench_report_20260309_130908.md`
- `build/logs/task30/pipeline_bench_report_20260309_132149.md`

Goals:

- Reduce full-workflow overhead for heavy benchmark tiers without touching the
  already-passing `extract_terms` stage runtime.
- Stop recloning the full `6000`-document bench slice into every reusable
  sandbox run.
- Keep heavy-tier runs deterministic by reusing a clean prepared fixture DB,
  not a previously mutated bench project in-place.

Result:

- Added a new `prepare_bench_fixture` scenario that builds a reusable fixture DB
  from the approved source DB and materializes the deterministic `BENCH_*`
  slice once.
- Added `--prepared-source-db` so heavy benchmark runs can reset the reusable
  sandbox from a fixture DB instead of the full approved source DB.
- Added `--reuse-bench-slice` so `extract_terms` can reuse the prepared
  `BENCH_*` project when the stored slice metadata matches:
  - `source_project_id`
  - `doc_limit`
  - copied document count
- Stored deterministic slice metadata in `dict_project.description` under the
  `bench_slice|...` contract and added parser/runtime validation for the new
  flags.
- Tightened source doc selection so the benchmark harness now applies SQL
  `LIMIT` before collecting doc ids for deterministic slices.

Observed evidence:

- Prepared fixture build on the approved DB completed successfully:
  - command shape:
    `prepare_bench_fixture --db-path J:\Project_Vibe\V_book\build\bench\hewiki_pipeline_ceiling_fixture.db --copy-target --source-db ...test.db --bench-project-name BENCH_PIPELINE_FIXTURE_CEILING --tier ceiling`
  - artifact: `build\logs\task30\pipeline_bench_report_20260309_130908.md`
  - `base_copy = 291.182 s`
  - `db_initialize = 1.668 s`
  - `bench slice clone = 412.378 s`
  - `overall wall = 706.530 s`
- Fixture-backed ceiling cycle on the reusable sandbox DB completed within the
  full workflow wall budget:
  - command shape:
    `extract_terms --reuse-working-db --reuse-bench-slice --pre-reset-sandbox --prepared-source-db J:\Project_Vibe\V_book\build\bench\hewiki_pipeline_ceiling_fixture.db --tier ceiling`
  - artifact: `build\logs\task30\pipeline_bench_report_20260309_132149.md`
  - `base_copy/pre_reset = 285.941 s`
  - `slice_clone = 14.499 s`
  - `pre_stage_overhead = 302.903 s`
  - `extract_terms stage = 1275.001 s`
  - `overall wall = 1580.967 s`
  - interpretation:
    - the heavy-tier bottleneck moved from full `slice_clone` overhead to the
      already-accepted `extract_terms stage`
    - the prepared fixture path brings the full `ceiling` workflow back under
      the current `1800 s` wall budget on this machine
- Operational contract for heavy tiers is now:
  - build or refresh the fixture DB explicitly with `prepare_bench_fixture`
  - run heavy tiers with `--prepared-source-db` and `--reuse-bench-slice`
  - keep `--post-cleanup-bench` disabled for this mode because the prepared
    `BENCH_*` slice is the reusable fixture payload

## Out of scope for PATCH-01

- Full dual-DB reference/user overlay architecture.
- Out-of-process worker architecture.
- Materialized large-project summary tables.
- Batch translate/audio coordinator expansion beyond the touched translation overlay paths.

## Evidence commands

```powershell
python -m app.main --self-check db_open --db-path "J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db"
python -m app.main --self-check health --db-path "J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db"
python scripts\perf_harness.py --db-path "J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db" --runs 5 --warmup 1 --out build\logs\task30\perf_harness_hewiki_test.json
python scripts\collect_queryplan_evidence.py --db-path "J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db" --project-id 1 --search-term wiki --out-dir build\logs\task30
```

## DoD for the first implementation wave

- Translation overlay worker uses read session only.
- Terms overlay results are request-sequenced and stale-safe.
- Translate Text dialog no longer force-terminates worker threads.
- Query-plan/perf artifacts record approved DB identity more explicitly.
- MT health no longer reports disabled providers as configured/active.
- Term extraction no longer clears existing terms before the collect phase succeeds.
- Term extraction no longer materializes full processed-document and sentence ORM
  collections during extraction.
- Term clustering no longer materializes the full project result set before inserts.
- Term clustering now persists mixed `source_kinds` and `member_doc_freq` correctly.
- Term extraction overwrite path now stages by doc batch with persisted run state.
- Term extraction can resume the latest matching staged run after cancel/failure.
- New targeted tests cover lifecycle and stale-result behavior.
- New targeted tests cover bounded term extraction ordering and minimal pipeline behavior.
- Existing touched-path regressions pass on local temp-root-safe pytest runs.
- Fixture-backed `ceiling` benchmark workflow passes the current `1800 s` full
  wall budget on the approved DB.
- Baseline + corrected future NLP checkpoint plan is preserved in
  `docs/NLP_PROCESS_CHECKPOINT_PLAN.md`.

### PATCH-12: Prepared fixture lifecycle hardening

Status: implemented on 2026-03-09

Files:

- `scripts/benchmarks/bench_reference_pipeline.py`
- `tests/test_pipeline_bench_runner_safety.py`
- `tests/test_pipeline_bench_argparse.py`
- `docs/NLP_PROCESS_CHECKPOINT_PLAN.md`
- `build/logs/task30/pipeline_bench_report_20260309_173819.md`
- `build/logs/task30/pipeline_bench_report_20260309_175023.md`

Goals:

- Add explicit maintenance lifecycle commands for prepared fixture DBs instead of
  treating `prepare_bench_fixture` as a one-shot bootstrap only.
- Provide a cheap `verify` step that proves a prepared fixture still matches the
  approved source DB and deterministic slice contract.
- Preserve the baseline `process with NLP` design context in repo docs and
  correct it after a deeper audit of the current UI + CLI processing paths.

Result:

- Added `refresh_bench_fixture` to rebuild a prepared fixture DB from the
  approved source DB and recreate the deterministic `BENCH_*` slice in one
  explicit maintenance step.
- Added `verify_bench_fixture` to validate:
  - fixture schema version vs approved source DB
  - deterministic source `doc_id` slice vs approved source DB
  - stored `bench_slice|...` metadata on the prepared `BENCH_*` project
  - prepared bench project document count vs expected deterministic slice size
- Added targeted parser/safety tests for the new fixture lifecycle scenarios and
  successful verification path.
- Saved the current `process with NLP` plan in
  `docs/NLP_PROCESS_CHECKPOINT_PLAN.md`, then corrected it after deeper review:
  - reference-scale NLP remains CLI-only
  - first production NLP implementation should use checkpointed writes on the
    main DB, not a copied benchmark-fixture workflow

Observed evidence:

- Live fixture refresh on the approved DB completed successfully:
  - command shape:
    `refresh_bench_fixture --db-path J:\Project_Vibe\V_book\build\bench\hewiki_pipeline_ceiling_fixture.db --copy-target --source-db ...test.db --bench-project-name BENCH_PIPELINE_FIXTURE_CEILING --tier ceiling`
  - artifact: `build\logs\task30\pipeline_bench_report_20260309_173819.md`
  - `base_copy/refresh = 289.567 s`
  - `bench slice clone = 419.950 s`
  - `overall wall = 712.619 s`
- Live fixture verification on the same prepared DB completed successfully:
  - command shape:
    `verify_bench_fixture --db-path J:\Project_Vibe\V_book\build\bench\hewiki_pipeline_ceiling_fixture.db --copy-target --source-db ...test.db --bench-project-name BENCH_PIPELINE_FIXTURE_CEILING --tier ceiling`
  - artifact: `build\logs\task30\pipeline_bench_report_20260309_175023.md`
  - `fixture schema version = 36`
  - `source schema version = 36`
  - `verify stage wall = 1.464 s`
  - `overall wall = 2.249 s`
  - all checks passed:
    - `schema_version_match`
    - `source_doc_ids_match`
    - `bench_metadata_match`
    - `bench_doc_count_match`

Operational contract:

- `prepare_bench_fixture` remains valid for first-time bootstrap.
- `refresh_bench_fixture` is now the explicit maintenance path when the prepared
  fixture must be rebuilt from the approved source DB.
- `verify_bench_fixture` is the fast preflight path before heavy-tier runs when
  the operator wants to confirm the prepared fixture is still current.
- For `ceiling` runs, the recommended order is now:
  - `verify_bench_fixture`
  - `refresh_bench_fixture` only if verify fails or the source contract changed
  - fixture-backed `extract_terms --reuse-bench-slice`

## NLP pre-implementation preflight (2026-03-09)

Before starting the next `process with NLP` implementation wave, the repo was
re-audited against the current code and docs, with fresh baseline evidence.

Confirmed evidence:

- targeted regression slice:
  - `tests/test_task12_fts_nlp.py`
  - `tests/test_reference_processing_guard.py`
  - `tests/test_process_service_remove_document_stats.py`
  - `tests/test_operations_center.py`
  - `tests/test_pipeline_throttler.py`
- result:
  - `47 passed in 38.94s`
  - artifact: `build/logs/nlp_prework/pytest_nlp_prework.log`
- live dry-run on the approved DB:
  - artifact: `build/logs/nlp_prework/process_reference_corpus_dry_run.log`
  - confirmed `387639 / 387639` docs already processed, `To process: 0`

Planning corrections captured from this preflight:

- resume/cancel/checkpoint proof for NLP cannot rely on the approved DB alone,
  because it currently has no remaining work to process
- the migration ledger is still `schema_meta(key='schema_version')`, not a
  separate `schema_version` table
- live `processor_run` remains in its legacy narrow shape and
  `DBService.recover_from_crash()` still only understands `status='running'`
- therefore the NLP foundation patch must include crash-recovery compatibility
  in the same wave as the new staged/resumable run-state model
- the saved/corrected plan now lives in `docs/NLP_PROCESS_CHECKPOINT_PLAN.md`
  and should be treated as the source of truth for the next NLP iteration

## PATCH-NLP-01 implemented (2026-03-09)

Files:

- `app/infra/migrations/037_nlp_run_state.sql`
- `app/infra/sa_models.py`
- `app/domain/dto.py`
- `app/services/process_service.py`
- `app/services/db_service.py`
- `tests/test_process_run_state_foundation.py`

Result:

- `processor_run` extended for foundational staged/resumable NLP state
- `process_document()` now fills `stage`, `docs_total`, `docs_failed`,
  `chunks_total`, `chunks_completed`, `last_doc_id`, `params_hash`,
  `error_message`
- crash recovery now marks recovered running rows with `stage='failed'` and
  a terminal error message

Validation:

- targeted regressions:
  - `29 passed in 80.68s`
  - artifact: `build/logs/nlp_prework/pytest_nlp_foundation.log`
- import smoke:
  - artifact: `build/logs/nlp_prework/import_smoke_nlp_foundation.log`
- approved DB migration applied successfully:
  - artifact: `build/logs/nlp_prework/hewiki_apply_migrations_nlp_foundation.log`
  - approved DB current schema: `37`
  - post-migration startup-compatible open:
    - artifact: `build/logs/nlp_prework/db_open_self_check_nlp_foundation_post_migration.json`
    - `ok=true`, `elapsed_ms=12`
  - live CLI dry-run after migration:
    - artifact: `build/logs/nlp_prework/process_reference_corpus_dry_run_post037.log`
    - `Current schema version: 37`
- approved DB live controlled probe succeeded and cleanup removed the temporary
  project:
  - artifact: `build/logs/nlp_prework/hewiki_live_nlp_foundation_probe.log`
  - artifact: `build/logs/nlp_prework/hewiki_live_nlp_foundation_cleanup_check.log`

## PATCH-NLP-02 implemented (2026-03-09)

Files:

- `app/services/process_service.py`
- `scripts/process_reference_corpus.py`
- `tests/test_process_batch_run_state.py`
- `tests/test_reference_processing_guard.py`

Result:

- `process_documents_batch()` now persists a batch-level resumable NLP run
  instead of relying on ephemeral loop counters only
- structured batch state is now emitted for:
  - `started`
  - `resumed`
  - `processing`
  - `chunk_complete`
  - `paused`
  - `cancelled`
  - `completed`
- the batch resume contract is now deterministic and gated by:
  - `params_hash`
  - `source_label`
  - `is_reprocess`
  - `doc_count`
  - `first_doc_id`
  - `last_doc_id`
  - full ordered-slice `doc_ids_hash`
- CLI reference processing gained `--resume-latest` and now routes through the
  same batch run-state path
- resumed runs keep the original persisted chunk contract, even if the operator
  reruns the CLI with a different `--chunk-size`

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
  - confirmed:
    - initial controlled batch run cancelled after one processed document
    - CLI `--resume-latest` reused the same `run_id=387620`
    - final batch state on the approved DB was:
      - `status='ok'`
      - `stage='completed'`
      - `docs_total=2`
      - `docs_processed=2`
      - `docs_failed=0`
      - `chunks_total=2`
      - `chunks_completed=2`
    - cleanup removed all temporary `BENCH_NLP_CLI_%` projects

Updated patch-order note:

- the next NLP step is now `PATCH-NLP-03` premium regular-project progress UI
  and worker lifecycle parity with staged `extract terms`
- `PATCH-NLP-04` is narrowed to explicit resume selection and CLI verify mode,
  because basic deterministic `--resume-latest` is already implemented

## PATCH-NLP-03 implemented (2026-03-09)

Files:

- `app/services/process_service.py`
- `app/ui/workers.py`
- `app/ui/documents_view.py`
- `app/ui/dialogs/nlp_process_progress_dialog.py`
- `tests/test_documents_process_progress_ui.py`
- `tests/test_task12_fts_nlp.py`
- `tests/test_process_batch_run_state.py`

Result:

- regular-project `Process with NLP` and `Re-process` now use the same staged
  batch run-state contract as the new NLP foundation:
  - structured state
  - cooperative pause/resume/cancel
  - deterministic `resume_latest`
- `reprocess_document()` now supports batch-run routing without creating extra
  per-document run rows during staged re-processing
- `DocumentsView` now opens a dedicated NLP progress dialog with:
  - run id
  - doc progress
  - chunk progress
  - last processed doc id
  - elapsed / last activity
  - recent activity log
  - pause/resume/cancel controls
- `DocumentsView.closeEvent()` no longer force-terminates the process worker; it
  requests cooperative cancellation and waits briefly for a safe checkpoint

Validation:

- targeted regressions:
  - `40 passed in 55.33s`
  - artifact: `build/logs/nlp_prework/pytest_nlp_patch03_ui_candidate.log`
- import smoke:
  - artifact: `build/logs/nlp_prework/import_smoke_nlp_patch03_ui.log`
  - result: `OK`
- approved DB live worker probe:
  - artifact: `build/logs/nlp_prework/hewiki_live_nlp_patch03_ui_probe.log`
  - confirmed on the real approved DB:
    - temporary regular project processed successfully via `ProcessWorker`
    - the same project then re-processed successfully via `ProcessWorker`
    - both batch runs persisted correct `processor_run` rows
    - cleanup removed the temporary project afterward

## PATCH-NLP-04 implemented (2026-03-09)

Files:

- `app/services/process_service.py`
- `scripts/process_reference_corpus.py`
- `tests/test_process_batch_run_state.py`
- `tests/test_process_reference_cli_verify.py`
- `docs/NLP_PROCESS_CHECKPOINT_PLAN.md`
- `docs/REFERENCE_PROJECT_GUIDE.md`

Result:

- CLI reference processing now supports:
  - explicit `--resume-run-id`
  - read-only `--verify-only` contract preflight
- `ProcessService.verify_batch_run_contract()` centralizes the deterministic
  batch verifier used by CLI selection and tests
- `process_documents_batch()` now supports `resume_run_id=` and rejects
  ambiguous `resume_latest + resume_run_id`
- auto-resume selection no longer treats `status='running'` rows as resumable
  candidates; only `paused`, `cancelled`, and `failed` are considered safe

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
  - postcheck artifact:
    `build/logs/nlp_prework/hewiki_cli_patch04_resume_verify_postcheck.log`

Updated patch-order note:

- `PATCH-NLP-05` remains optional future offline/staging scope only if product
  requirements later demand detached processing

## PATCH-CONV-01 implemented (2026-03-09)

Files:

- `app/domain/dto.py`
- `app/services/term_extraction_service.py`
- `app/ui/dialogs/term_extraction_progress_dialog.py`
- `app/ui/terms_view.py`
- `tests/test_term_extraction_service_large_project.py`
- `tests/test_terms_extract_progress_ui.py`
- convergence/task docs as needed

Result:

- staged term extraction state payload now carries NLP-aligned baseline fields:
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
- term extraction now emits explicit `paused` / `resumed` phases during the
  batch checkpoint wait
- finalize-state term extraction no longer emits blank `phase` values
- Terms progress dialog now consumes structured state for activity logging,
  which reduces UI wiring drift versus the NLP progress dialog

Validation:

- targeted convergence regressions:
  - `46 passed in 205.80s`
  - artifact: `build/logs/nlp_prework/pytest_nlp_terms_convergence.log`
- approved DB live convergence probe:
  - artifact: `build/logs/nlp_prework/hewiki_live_terms_convergence_probe.log`
  - confirmed on the approved DB:
    - the staged term extraction state stream included `paused` and `resumed`
    - `saw_empty_phase=false`
    - completed state carried the aligned metadata fields
    - cleanup removed the temporary probe project

## PATCH-CONV-02 implemented (2026-03-09)

Files:

- `app/ui/dialogs/staged_operation_progress_dialog.py`
- `app/ui/dialogs/nlp_process_progress_dialog.py`
- `app/ui/dialogs/term_extraction_progress_dialog.py`
- `tests/test_staged_operation_progress_dialogs.py`
- convergence/task docs as needed

Result:

- NLP and Terms staged long-operation dialogs now share one reusable base
  implementation for:
  - layout
  - structured state rendering
  - activity log
  - heartbeat labels
  - pause/resume/cancel lifecycle
  - cooperative close behavior
- operation-specific wording remains local to the NLP and Terms wrappers, so the
  visible UX remains stable while duplicated dialog logic is removed
- direct Qt regressions now cover the real dialog classes, not only the parent
  view wiring

Validation:

- targeted shared-dialog regressions:
  - `28 passed in 93.79s`
  - artifact: `build/logs/nlp_prework/pytest_nlp_terms_shared_dialog.log`
- import smoke:
  - artifact: `build/logs/nlp_prework/import_smoke_terms_nlp_shared_dialog.log`
  - result: `OK`
- approved DB app-open smoke:
  - artifact:
    `build/logs/nlp_prework/db_open_self_check_terms_nlp_shared_dialog.json`
  - confirmed `db_open ok` on the approved DB

## PATCH-CONV-03 implemented (2026-03-09)

Files:

- `app/infra/migrations/038_sentence_nlp_snapshot.sql`
- `app/infra/nlp_snapshot_codec.py`
- `app/infra/sa_models.py`
- `app/services/process_service.py`
- `app/services/term_extraction_service.py`
- `tests/test_sentence_nlp_snapshot_reuse.py`
- `tests/test_term_extraction_service_large_project.py`
- convergence/task docs as needed

Result:

- NLP processing now persists sentence-level token/POS/lemma snapshots in
  `sentence_nlp_snapshot` while processing `document_sentence` rows
- term extraction now prefers persisted snapshots when the stored
  `sentence_text_hash` still matches the live sentence text and falls back to
  runtime reparse only when the snapshot is missing or stale
- this removes the main confirmed duplicate NLP work for already processed
  documents without reopening the long-operation UI or benchmark contracts
- approved `hewiki_gpu_processing test.db` is now at `schema_version=38`

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
    - migration `038` was applied
    - a temporary project/document produced `2` sentence snapshots
    - term extraction completed successfully even when its NLP engine was
      replaced with a failing stub
    - cleanup removed the temporary probe project with no leftovers

## Coverage audit and cleanup follow-up (2026-03-10)

Files:

- `app/services/project_service.py`
- `tests/test_project_delete_fast.py`
- `docs/NLP_PROCESS_CHECKPOINT_PLAN.md`
- `docs/TERM_EXTRACTION_CHUNKED_PLAN.md`
- task30 docs as needed

Result:

- both real hewiki DBs were re-checked against the current migration set
- main install DB advanced from `schema_version=35` to `schema_version=38`
- coverage audit showed that legacy project-attached processed docs currently
  have `0.0%` sentence-snapshot coverage on both DBs
- this means the next useful convergence patch is snapshot backfill, not
  freshness/version gating
- the audit also exposed a real cleanup regression: fast `delete_project()`
  had not been explicitly deleting `sentence_nlp_snapshot` while
  `foreign_keys=OFF`, which could leave orphan rows after temporary probes
- `delete_project()` now explicitly deletes `sentence_nlp_snapshot` rows before
  deleting `document_sentence`

Validation:

- migration/runtime evidence:
  - artifact: `build/logs/nlp_coverage/db_migration_probe.log`
  - artifacts:
    - `build/logs/nlp_coverage/db_open_main_install.json`
    - `build/logs/nlp_coverage/db_open_dev_test.json`
- coverage evidence:
  - artifact:
    `build/logs/nlp_coverage/sentence_snapshot_coverage_probe_after_cleanup.jsonl`
  - artifact:
    `build/logs/nlp_coverage/orphan_doc_hierarchy_probe.jsonl`
- orphan cleanup evidence:
  - artifact:
    `build/logs/nlp_coverage/orphan_sentence_snapshot_cleanup.log`
  - confirmed:
    - main install orphan snapshot rows `0 -> 0`
    - dev/test orphan snapshot rows `2 -> 0`
- targeted delete/snapshot regressions:
  - `14 passed in 111.45s`
  - artifact:
    `build/logs/nlp_coverage/pytest_project_delete_snapshot_cleanup_targeted.log`
- prebuild lifecycle smoke:
  - artifact:
    `build/logs/nlp_coverage/prebuild_validate_project_delete_snapshot_cleanup.log`
  - result: all checks passed
- live dev/test DB delete probe:
  - artifact:
    `build/logs/nlp_coverage/hewiki_dev_test_snapshot_delete_probe.log`
  - confirmed:
    - temporary processed doc produced `2` snapshots
    - deleting the temporary project left `orphan_after=0`
    - no project leftovers remained

## Snapshot backfill follow-up implemented (2026-03-10)

Files:

- `app/services/process_service.py`
- `scripts/process_reference_corpus.py`
- `tests/test_sentence_snapshot_backfill_batch.py`
- `tests/test_process_reference_cli_verify.py`
- `docs/NLP_PROCESS_CHECKPOINT_PLAN.md`
- `docs/REFERENCE_PROJECT_GUIDE.md`
- `docs/TERM_EXTRACTION_CHUNKED_PLAN.md`
- task30 docs as needed

Result:

- the coverage audit outcome was acted on directly:
  legacy processed docs can now be enriched through a dedicated CLI-first
  snapshot backfill path instead of waiting for a future full reprocess
- `process_reference_corpus.py` now supports:
  - `--backfill-snapshots`
  - `--coverage-only`
  - snapshot-backfill `--verify-only`
- `ProcessService` now reuses the current batch `processor_run` model for
  resumable snapshot backfill via the explicit `snapshot_backfill_v1` contract
- the deterministic resume slice is the full processed-doc set for the project,
  not the shrinking "still missing snapshots" subset
- backfill only writes missing `sentence_nlp_snapshot` rows and does not touch:
  - document NLP status
  - lemma tables
  - term tables

Validation:

- targeted regressions:
  - `29 passed in 158.98s`
  - artifact: `build/logs/nlp_backfill/pytest_snapshot_backfill.log`
- import smoke:
  - artifact: `build/logs/nlp_backfill/import_smoke_snapshot_backfill.log`
  - result: `OK`
- live approved dev/test DB probe:
  - setup artifact:
    `build/logs/nlp_backfill/live_cli_probe_setup.log`
  - coverage-only artifact:
    `build/logs/nlp_backfill/live_cli_probe_coverage.log`
  - backfill artifact:
    `build/logs/nlp_backfill/live_cli_probe_backfill.log`
  - post-check artifact:
    `build/logs/nlp_backfill/live_cli_probe_postcheck.log`
  - confirmed:
    - temporary processed docs started at `0.0%` coverage
    - the run created `4` sentence snapshots for `2` docs
    - cleanup left no temporary project leftovers

Current next step:

- do not introduce freshness/version gating yet
- first measure coverage after operators run the new backfill path on legacy
  long-lived projects
- only then decide whether a separate freshness/integrity hardening patch is
  warranted

## Re-process bugfix on approved dev/test DB (2026-03-10)

Files:

- `app/services/process_service.py`
- `app/ui/documents_view.py`
- `app/ui/dialogs/staged_operation_progress_dialog.py`
- `app/infra/migrations/039_reprocess_fk_delete_indexes.sql`
- `tests/test_process_service_remove_document_stats.py`
- `tests/test_documents_process_progress_ui.py`
- `tests/test_staged_operation_progress_dialogs.py`
- `tests/test_perf_indexes_present.py`

Result:

- fixed the live `re-process` stall reproduced on project `ID=5`
  (`тест 9 марта`) in the approved dev/test DB
- the stall was traced to project-wide orphan-lemma cleanup during
  `remove_document_stats()`
- orphan cleanup is now restricted to the current document's lemma ids, and the
  missing `lemma_id` delete-cascade indexes were added in migration `039`
- the regular-project NLP dialog now shows immediate per-document activity
  instead of appearing stuck on `Created NLP batch run`
- cancel now gives immediate visible feedback in the dialog and still cancels at
  the next safe document checkpoint

Evidence:

- resumed batch run artifact:
  `build/logs/nlp_reprocess_project5/reprocess_project5_batch_postfix.jsonl`
- run/doc post-check:
  `build/logs/nlp_reprocess_project5/reprocess_project5_postcheck.json`
- worker cancel probe:
  `build/logs/nlp_reprocess_project5/reprocess_project5_worker_cancel.json`

Observed on the same approved dev/test DB:

- `remove_document_stats()` for doc `387643`: `0.711 s`
- resumed run `387617`: both docs completed in about `16.5 s`
- worker cancel run `387620`: cancel acknowledged and stopped at the next
  document boundary

Coverage choice after this fix:

- `ID=5` is already at `100.0%` sentence snapshot coverage after the re-process
  probes and is no longer a useful decision-driving backfill target
- `ID=6` remains a valid tiny smoke target with `0.0%` coverage on `1` doc
- `ID=1` (`Hebrew Wikipedia Baseline`) remains the meaningful legacy corpus for
  deciding whether a later freshness/version hardening patch is warranted

## Full-scale ID=1 snapshot-backfill probe (2026-03-10)

Result on the approved dev/test DB:

- pre-run `coverage-only` confirmed:
  - `387639` processed docs
  - `0.0%` sentence snapshot coverage
  - `0.0%` full-doc coverage
- full backfill run `387621` completed:
  - `387639/387639` docs
  - `0` errors
  - `78/78` chunks
  - `6300.1 s` wall-clock, about `105` minutes

Critical blocker discovered immediately after completion:

- post-run coverage verification failed with `database disk image is malformed`
- `PRAGMA quick_check` on the same dev/test DB confirmed corruption in the
  `sentence_nlp_snapshot` table btree

Task30 consequence:

- the current next step is no longer freshness/version hardening
- the next step is integrity hardening for the full-scale snapshot-backfill
  path and safe restore guidance for the dev/test DB
- the main install DB must not receive the same full-scale backfill run until
  this integrity issue is understood and fixed

## Snapshot-backfill integrity hardening follow-up (2026-03-10)

Files:

- `app/services/process_service.py`
- `scripts/process_reference_corpus.py`
- `scripts/repair_db_corruption.py`
- `tests/test_sentence_snapshot_backfill_batch.py`
- `tests/test_process_reference_cli_verify.py`
- `tests/test_repair_db_corruption_diagnose_ok.py`
- `tests/test_repair_db_corruption_detects_corruption.py`
- `tests/test_repair_db_corruption_recover_flow.py`

Result:

- snapshot backfill completion is now gated by a physical integrity check, not
  just logical batch counters
- the post-run path executes:
  - a configurable checkpoint step for diagnostics
  - `PRAGMA quick_check(10)`
- if integrity fails, the batch no longer lands in `ok/completed`; it is
  persisted as:
  - `status='failed'`
  - `stage='failed_integrity'`
  - `RunError.stage='integrity_check'`
- the reference CLI now exits with a controlled error on integrity failure
- corruption diagnosis is sharper:
  - `sentence_nlp_snapshot` gets an explicit probe
  - quick-check rootpages are mapped back to `sqlite_master`
  - valid partial `tm_entry` indexes no longer produce false corruption noise

Validation:

- targeted + adjacent regressions:
  - `44 passed in 283.62s`
- live diagnose on the corrupted approved dev/test DB:
  - `build/logs/nlp_integrity/repair_diagnose_test_db_verbose.log`
  - `build/logs/db_corruption_repair_20260310_073008.json`
- confirmed:
  - the damaged rootpage maps directly to `sentence_nlp_snapshot`
  - `tm_entry` probe is healthy on the same file

Next step:

- still do not run another full-scale backfill on either hewiki DB yet
- repair or replace the damaged dev/test DB first
- only then repeat:
  - `coverage-only`
  - full backfill on `ID=1`
  - post-run coverage measurement
- only after a clean rerun should freshness/version hardening be reconsidered

## Dev/test DB recovery from safe backup (2026-03-10)

Files:

- `scripts/repair_db_corruption.py`
- `tests/test_repair_db_corruption_recover_flow.py`
- `docs/NLP_PROCESS_CHECKPOINT_PLAN.md`
- `docs/REFERENCE_PROJECT_GUIDE.md`

Result:

- the approved dev/test DB was restored from the matching safe backup:
  - source backup:
    `backups\backup_20260310_033538_pre_migration_38_to_39.db`
  - restored target:
    `hewiki_gpu_processing test.db`
- the corrupted post-backfill DB was preserved separately as:
  - `hewiki_gpu_processing test.corrupt_20260310_081113.db`
- restore then re-applied migrations and brought the restored DB back to:
  - `schema_version=39`
- `db_open` is healthy again on the restored target
- `coverage-only` works again on the restored target:
  - `ID=1`: `0.0%` snapshot coverage on `387639` processed docs
  - `ID=5`: `0.0%` snapshot coverage on `2` docs
  - `ID=6`: project/doc presence confirmed

Operational meaning:

- the development/test DB is usable again
- the restore proves the backup-based recovery path is the practical local
  incident-response strategy on this machine, where `sqlite3.exe` is still not
  available
- this does not unblock full-scale backfill:
  the durability bug is still open, only the environment has been recovered

## Bounded snapshot-backfill root-cause probe (2026-03-10)

Files:

- `scripts/process_reference_corpus.py`
- `tests/test_process_reference_cli_verify.py`
- `docs/NLP_PROCESS_CHECKPOINT_PLAN.md`

Result:

- added CLI-only forensic probes for snapshot backfill:
  - `--probe-out`
  - `--probe-every-chunks`
  - `--probe-quick-check-timeout`
- bounded hewiki sandbox run completed on:
  - `build\bench\hewiki_snapshot_diag.db`
  - `ID=1`
  - `--max-docs 20000`
  - `--chunk-size 5000`
- artifacts:
  - `build/logs/nlp_root_cause/snapshot_backfill_20000.log`
  - `build/logs/nlp_root_cause/snapshot_backfill_probe_20000.jsonl`
  - `build/logs/nlp_root_cause/snapshot_backfill_probe_20000_summary.json`
  - `build/logs/nlp_root_cause/sandbox_postrun_diagnose.log`

Observed:

- `20000/20000` docs completed successfully
- post-run diagnose returned `status=OK`
- no non-timeout `quick_check` failures were recorded in chunk probes
- this means corruption did not reproduce early in the run

Interpretation:

- current evidence points away from an immediate per-document write bug
- the more likely risk area is now late-scale behavior:
  - accumulated snapshot table size
  - long-run checkpoint/flush discipline
  - or a threshold hit much later than the first `20k` docs

## Late-scale sandbox threshold narrowed (2026-03-10)

Files:

- `app/services/process_service.py`
- `scripts/process_reference_corpus.py`
- `tests/test_sentence_snapshot_backfill_batch.py`
- `tests/test_process_reference_cli_verify.py`
- `build/logs/nlp_root_cause/snapshot_backfill_probe_20001_60000_summary.json`
- `build/logs/nlp_root_cause/snapshot_backfill_60001_120000.log`
- `build/logs/nlp_root_cause/snapshot_backfill_probe_60001_120000_summary.json`
- `build/logs/nlp_root_cause/sandbox_bounded_probe_after_120000.json`
- `build/logs/nlp_root_cause/snapshot_backfill_0_120000_checkpoint_none.log`
- `build/logs/nlp_root_cause/snapshot_backfill_probe_0_120000_checkpoint_none_summary.json`
- `build/logs/nlp_root_cause/sandbox_bounded_probe_after_120000_checkpoint_none.json`

Result:

- added `--doc-offset` for reproducible late-scale slice probes through the
  official reference-processing CLI
- added `--integrity-checkpoint-mode` for snapshot-backfill forensic control
- the same disposable-sandbox workload now gives a direct checkpoint control:
  - `60001..120000` with the old `truncate` integrity mode reproduced
    corruption in `sentence_nlp_snapshot`
  - a fresh `0..120000` control run with `integrity-checkpoint-mode=none`
    completed successfully
- snapshot-backfill integrity verification now defaults to `none`; aggressive
  checkpoint modes remain explicit diagnostic overrides

Interpretation:

- evidence now points more narrowly at the final `TRUNCATE` checkpoint/flush
  path than at the per-document backfill write loop itself
- the safer current default is to verify integrity without forcing a
  `TRUNCATE` checkpoint at the end of the run

Current next step:

- keep using disposable sandbox DBs for further large-scale durability probing
- only after a clean full-scale rerun on the restored hewiki dev/test DB should
  coverage-after and freshness/version work resume

## Full-scale rerun with safer integrity default still fails on approved dev/test DB (2026-03-10)

Files:

- `build/logs/nlp_full_rerun_id1/coverage_before_full_rerun.log`
- `build/logs/nlp_full_rerun_id1/snapshot_backfill_full_id1.log`
- `build/logs/nlp_full_rerun_id1/snapshot_backfill_probe_full_id1_summary.json`
- `build/logs/nlp_full_rerun_id1/repair_diagnose_after_full_rerun.log`
- `build/logs/nlp_full_rerun_id1/bounded_probe_after_full_rerun.json`
- `build/logs/nlp_full_rerun_id1/restore_test_db_after_failed_full_rerun.log`
- `build/logs/nlp_full_rerun_id1/db_open_after_restore_from_081114.json`

Result:

- reran full `ID=1` snapshot backfill on the restored approved dev/test DB with:
  - `--integrity-checkpoint-mode none`
  - `--chunk-size 5000`
  - chunk probes every `5` chunks
- runtime was about `132` minutes
- logical batch counters still finished cleanly:
  - `docs_processed=387639`
  - `docs_failed=0`
- physical integrity still failed at the end:
  - `status='failed'`
  - `stage='failed_integrity'`
  - `PRAGMA quick_check(10)` reported corruption again
- diagnose still maps the damaged btree to `sentence_nlp_snapshot`

Interpretation:

- the previous `TRUNCATE` checkpoint issue was only part of the failure surface
- safer default `none` remains the correct mitigation for the old checkpoint bug
- but the full-scale backfill path is still unsafe because the large-scale
  snapshot write pattern itself can corrupt the table

Operational follow-up:

- `hewiki_gpu_processing test.db` was restored again after this failed rerun
- restoration in this wave used:
  - `backups\backup_20260310_081114_pre_migration_38_to_39.db`
- validated post-restore:
  - `schema_version=39`
  - projects `1/5/6` present

Current next step:

- do not resume freshness/version work
- move to a new storage-level redesign wave for `sentence_nlp_snapshot`
  full-scale writes

## Snapshot backfill storage redesign wave (2026-03-10)

Status:

- implemented and validated on the approved dev/test DB

Files:

- `app/infra/migrations/040_sentence_nlp_snapshot_stage.sql`
- `app/infra/sa_models.py`
- `app/services/process_service.py`
- `scripts/process_reference_corpus.py`
- `tests/test_sentence_snapshot_backfill_batch.py`
- `tests/test_process_reference_cli_verify.py`
- `tests/test_project_delete_fast.py`

What changed:

- added `sentence_nlp_snapshot_stage`
- legacy snapshot backfill now uses:
  - per-document staging
  - bounded merge batches into `sentence_nlp_snapshot`
  - bounded physical verification on every super-chunk boundary
- CLI controls added:
  - `--merge-batch-size`
  - `--segment-quick-check-timeout`
- fast project delete now explicitly clears stage rows too

Validation:

- targeted + adjacent regressions:
  - `57 passed in 300.05s`
  - artifact: `build/logs/nlp_redesign_preflight/pytest_redesign_regression.log`
- both real hewiki DBs now at:
  - `schema_version=40`
  - `sentence_nlp_snapshot_stage` present
- bounded real run on `hewiki_gpu_processing test.db`:
  - `ID=1`
  - `max_docs=10000`
  - `chunk_size=5000`
  - `merge_batch_size=1000`
  - `segment_quick_check_timeout=0.5`
  - runtime `1780.3 s`
  - run `387618` finished `ok/completed`
  - `stage_rows_remaining=0`
  - post-run `db_open` healthy

Operational interpretation:

- the redesign is good enough for bounded large-scale backfill on the real
  dev/test DB
- this is a real step forward from the old direct-write path, but it still does
  not justify an immediate fresh full-scale rerun on all `387639` docs
- the next evidence step should be a larger staged slice, not a return to
  freshness/version work

## Staged tier extended on real dev/test DB (2026-03-11)

Status:

- completed successfully

Artifacts:

- `build/logs/nlp_stage_next/coverage_before_50000.log`
- `build/logs/nlp_stage_next/snapshot_backfill_10001_50000.log`
- `build/logs/nlp_stage_next/snapshot_backfill_probe_10001_50000.jsonl`
- `build/logs/nlp_stage_next/probe_summary_10001_50000.json`
- `build/logs/nlp_stage_next/coverage_after_50000.log`
- `build/logs/nlp_stage_next/db_open_after_50000.json`
- `build/logs/nlp_stage_next/postrun_probe_50000.json`

Observed:

- extended the approved `hewiki_gpu_processing test.db` from the first `10k`
  staged coverage to `50k` cumulative docs by running:
  - `doc_offset=10000`
  - `max_docs=40000`
  - `chunk_size=5000`
  - `merge_batch_size=1000`
  - `segment_quick_check_timeout=0.5`
- run `387619` completed with:
  - `status='ok'`
  - `docs_processed=40000`
  - `docs_failed=0`
  - `chunks_completed=8/8`
  - `stage_rows_remaining=0`
- post-run `db_open` stayed healthy
- coverage on `ID=1` increased to:
  - `49999` fully covered docs
  - `20.1938%` sentence coverage
  - `12.8983%` full-doc coverage

Operational interpretation:

- the redesigned backfill path now has real-db evidence beyond the initial
  `10k` slice
- the next rational step is a larger staged tier, e.g. `120k` cumulative docs,
  before any fresh full-scale rerun discussion

## Staged tier extended on real dev/test DB to 120k cumulative docs (2026-03-11)

Status:

- completed successfully

Artifacts:

- `build/logs/nlp_stage_120k/db_open_before_120k.json`
- `build/logs/nlp_stage_120k/snapshot_backfill_probe_50001_120000.jsonl`
- `build/logs/nlp_stage_120k/probe_summary_50001_120000.json`
- `build/logs/nlp_stage_120k/run_summary_50001_120000.json`
- `build/logs/nlp_stage_120k/coverage_after_120k.log`
- `build/logs/nlp_stage_120k/db_open_after_120k.json`
- `build/logs/nlp_stage_120k/postrun_probe_120k.json`

Observed:

- extended the approved `hewiki_gpu_processing test.db` from `50k` to `120k`
  cumulative covered docs by running:
  - `doc_offset=50000`
  - `max_docs=70000`
  - `chunk_size=5000`
  - `merge_batch_size=1000`
  - `segment_quick_check_timeout=0.5`
  - `integrity_checkpoint_mode=none`
- run `387620` completed with:
  - `status='ok'`
  - `docs_processed=70000`
  - `docs_failed=0`
  - `chunks_completed=14/14`
  - `stage_rows_remaining=0`
  - runtime `3495.7 s`
- post-run `db_open` stayed healthy
- coverage on `ID=1` increased to:
  - `119999` fully covered docs
  - `38.1812%` sentence coverage
  - `30.9564%` full-doc coverage

Operational interpretation:

- the redesigned backfill path now has real-db evidence through `120k`
  cumulative docs on the approved dev/test DB
- the next rational step is another materially larger staged tier, e.g. `250k`
  cumulative docs, before any new full-scale rerun discussion

## Controlled hold-state for snapshot backfill track

Task30 status after the `120k` cumulative evidence wave:

- bounded validation is sufficient for the current engineering decision
- no new expensive full run is required immediately
- full-volume validation is deferred intentionally
- main DB execution remains blocked
- freshness/version work remains blocked

The decision gate and future heavy-run package are documented in:

- `docs/NLP_SNAPSHOT_BACKFILL_DECISION_GATE.md`
