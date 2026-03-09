# Task 30 Implementation Plan (2026-03-09)

## Scope

This plan is based on the approved Task 30 audit executed against:

- DB path: `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`
- Verified runtime contract: `python -m app.main --db-path "<path above>"`
- Verified schema version on target DB at initial Task 30 audit: `35`
- Current schema version on the same DB after migration `037_nlp_run_state`: `37`

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
