# Engineering Control And Optimization Roadmap

Status date: `2026-03-11`

## Scope

This document freezes the next priority engineering branch after:

- bounded `sentence_nlp_snapshot` backfill validation,
- snapshot readiness observability rollout,
- runtime decision-gate hardening for protected reference DB targets.

It is the source of truth for what should be optimized next, what should stay in
hold-state, and which processes/data remain weakly controlled at hewiki scale.

## Current completed baseline

Already implemented and validated:

- checkpointed `process with NLP` with premium progress UX,
- bounded staged snapshot backfill on the approved dev/test hewiki DB,
- backup/restore and integrity guardrails for damaged DB recovery,
- snapshot readiness and reuse observability surfaces in Documents and Terms,
- runtime heavy-write decision gate for protected reference DB targets.

This means the next branch is no longer about adding more backfill UX or
another expensive validation run.

## What remains weakly controlled

### P0 process risks

1. **Bundle import lock windows and cancelability**
   - `app/services/project_exchange/import_engine.py`
   - Import still needs tighter bounded transactional phases and explicit
     cooperative cancel checks at safe boundaries across the whole import path.
   - This remains the highest-value controllability fix because it affects both
     real operator use and concurrent write contention.

2. **Runtime write contention discipline**
   - `app/infra/db.py`
   - `app/services/db_service.py`
   - `app/infra/db_retry.py`
   - `app/services/operations_center.py`
   - Read/write separation is only partial, retry discipline is selective, and a
     true single-writer baseline is still missing.

3. **Large derived processing data governance**
   - `lemma_doc_stat`
   - `lemma_project_stat`
   - `sentence_nlp_snapshot`
   - `processor_run`
   - `run_error`
   - These growth-heavy artifacts are now the next practical controllability gap
     after the import/runtime/picker P0 fixes.

### P1 data-governance risks

1. **Large derived NLP tables**
   - `lemma_doc_stat`
   - `lemma_project_stat`
   - These are inherently large and not realistically "optimizable away".
   - What is missing is better lifecycle governance, maintenance strategy, and
     operator visibility into size/growth/cost.

2. **Large snapshot payloads**
   - `sentence_nlp_snapshot`
   - Snapshot persistence is now safer, but payload growth and long-term
     retention/inspection policy are still underdefined.

3. **Operational run telemetry growth**
   - `processor_run`
   - `run_error`
   - These are useful operational records, but they still need an explicit
     retention/cleanup contract before they become another unmanaged growth path.

4. **Audio cache uniqueness contract**
   - `audio_asset`
   - The cache lifecycle is partially hardened, but row uniqueness still relies
     on the legacy weak key instead of a fully content-addressed contract.

## What is intentionally not the next target

The following tracks remain intentionally deferred:

- full-volume snapshot backfill on the working dev/test DB,
- any snapshot backfill on the main install DB,
- freshness/version hardening,
- speculative storage changes without a new decision-gate trigger.

See also:

- `docs/NLP_SNAPSHOT_BACKFILL_DECISION_GATE.md`

## Priority roadmap

### PATCH-P0-01: Import cancelability and bounded lock windows

Goal:

- make bundle import cooperatively cancelable,
- reduce long write-lock windows,
- keep rollback/cleanup deterministic.

Primary files:

- `app/services/project_exchange/import_engine.py`
- `app/services/project_exchange/worker.py`
- `app/ui/dialogs/project_exchange_dialogs.py`
- `app/ui/app_window.py`
- `tests/test_project_exchange.py`
- `tests/test_import_chunking_write_gate.py`

Expected output:

- cancel acknowledged at safe table/chunk boundaries,
- no partial leaked rows after cancel/failure,
- bounded write phases with better evidence logging.

Status after first implementation wave:

- implemented on `2026-03-11`
- refined from the older audit finding: the import path is no longer fully
  monolithic, so the practical gap was narrower than the original P0 note
  suggested
- the concrete fix was:
  - keep `library`, `dict_project`, `tm_global` on the monolithic/special path
  - move the remaining generic import tables to bounded gate-batches
  - add `cancel_check` before entering the transactional write callback
  - emit finer progress text for batched table phases without changing the UI
    signal contract

Evidence:

- regressions:
  - `tests/test_import_chunking_write_gate.py`
  - `tests/test_project_exchange.py`
  - result: `26 passed`
- controlled benchmark on copied hewiki dev/test DB:
  - baseline artifact: `build/logs/import_concurrent_save_metrics_20260311_060844.json`
  - post-patch artifact: `build/logs/import_concurrent_save_metrics_20260311_063604.json`
  - observed:
    - `source_document` max hold reduced from `184.137 ms` to `101.993 ms`
    - max concurrent save latency reduced from `441.615 ms` to `377.883 ms`
    - import remained successful and `SQLITE_BUSY` stayed at `0`

Remaining note:

- this patch improves import controllability and reduces lock windows, but it
  does not yet deliver the broader runtime write-governance baseline
- the next priority remains `PATCH-P0-02`

### PATCH-P0-02: Runtime DB write-governance baseline

Goal:

- establish a clearer runtime contract for read vs write DB work,
- reduce `SQLITE_BUSY` incidents,
- make write behavior more deterministic under contention.

Primary files:

- `app/infra/db.py`
- `app/services/db_service.py`
- `app/infra/db_retry.py`
- `app/services/operations_center.py`
- targeted high-contention service call sites

Expected output:

- clearer read/write session routing,
- stronger retry/rollback baseline,
- lightweight single-writer discipline for high-contention flows.

Status after first implementation wave:

- implemented on `2026-03-11`
- refined from the broader roadmap note: the repo already had read/write engine
  separation in `app/infra/db.py` and `app/services/db_service.py`
- the practical gap was narrower and more runtime-focused:
  - global heavy-operation slot semantics in `app/services/operations_center.py`
  - advisory throttler updated to the same global heavy-slot contract in
    `app/services/pipeline_throttler.py`
  - hard slot claim at worker runtime for:
    - NLP processing
    - term extraction
    - ingest
    - document delete
    - dictionary import
    - project import
    - pronunciation / sentence niqqud bootstrap

Concrete output of this wave:

- heavy categories now share one process-wide slot instead of per-category
  independence
- workers that mutate the DB now fail fast with a user-facing busy error if the
  slot is already occupied
- the advisory UI check and the runtime worker guard now agree on what counts
  as a conflicting heavy operation

Evidence:

- regressions:
  - `tests/test_operations_center.py`
  - `tests/test_pipeline_throttler.py`
  - `tests/test_documents_process_progress_ui.py`
  - `tests/test_terms_extract_progress_ui.py`
  - `tests/test_pronunciation_bootstrap_idempotent_ui.py`
  - `tests/test_heavy_worker_slot_guard.py`
  - result: `43 passed`
- broader governance/import/read-write slice:
  - `tests/test_import_chunking_write_gate.py`
  - `tests/test_project_exchange.py`
  - `tests/test_rw_engine_split.py`
  - `tests/test_db_retry.py`
  - `tests/test_sqlite_busy_retry.py`

Remaining note:

- this wave establishes the runtime writer-governance baseline without a large
  service-layer refactor
- read/write split remains the architectural baseline
- broader mutation-path enrollment or a shared write-governance helper may
  still be a future follow-up if new contention evidence appears
- the next active priority is now `PATCH-P0-03`

### PATCH-P0-03: Document picker staged first-paint / SLO recovery

Goal:

- remove the dominant user-facing latency path in daily picker navigation.

Primary files:

- `app/services/document_service.py`
- `app/ui/dialogs/document_picker_dialog.py`
- `app/ui/workers.py`
- `tests/test_document_picker_flow.py`
- `tests/test_perf_fts_document_picker.py`
- `tests/test_documents_pagination_sort_search.py`

Expected output:

- rows rendered before total-count/tag side work,
- repeated picker reloads avoid re-fetching project top tags,
- no regression in deterministic paging behavior or anti-stale request handling.

Status after implementation wave:

- implemented on `2026-03-11`
- refined by live evidence on the approved hewiki dev/test DB:
  - query-level `picker_page_search` was already back within SLO after the
    earlier FTS-backed service path work
  - the remaining daily-navigation cost had shifted to the worker path:
    `rows + count + top-tags` sequencing inside the picker dialog
- the practical fix was therefore narrower than the original roadmap item:
  - keep the existing `DocumentService` search path
  - switch `ProjectDocumentsPageWorker` / `DocumentPickerDialog` to staged
    `rows -> count -> top-tags`
  - cache project top tags per dialog instance so repeated reloads do not pay
    the `get_project_frequent_tags()` cost again

Evidence:

- baseline worker-path breakdown on live hewiki dev/test DB:
  - `build/logs/picker_p003/picker_worker_breakdown_pre_patch.json`
  - observed p95:
    - `rows = 0.168s`
    - `count = 0.103s`
    - `top_tags = 0.273s`
    - `total worker path = 0.523s`
- post-patch staged breakdown on the same DB:
  - `build/logs/picker_p003/picker_staged_breakdown_post_patch.json`
  - observed p95:
    - `rows-first paint = 0.161s`
    - `rows + count (repeat reload, no tag refetch) = 0.248s`
- regressions:
  - `tests/test_document_picker_flow.py`
  - `tests/test_perf_fts_document_picker.py`
  - `tests/test_documents_pagination_sort_search.py`
  - result: `35 passed`

Remaining note:

- the dominant picker debt is no longer a blocking P0 item
- future picker work should now be treated as incremental UI/perf polish unless
  new hewiki evidence shows a fresh regression

### PATCH-P1-01: Governance for large derived processing data

Goal:

- distinguish inevitable large data from unmanaged growth,
- add lifecycle/retention/reporting strategy for heavy derived artifacts.

Primary targets:

- `lemma_doc_stat`
- `lemma_project_stat`
- `sentence_nlp_snapshot`
- `processor_run`
- `run_error`

Expected output:

- documented lifecycle rules,
- operator visibility into growth/ownership,
- clear future maintenance hooks.

Status after implementation wave:

- implemented on `2026-03-11`
- refined by live evidence on the approved hewiki dev/test DB:
  - exact project counts remain affordable for:
    - `lemma_doc_stat`
    - `lemma_project_stat`
    - `processor_run`
    - `run_error`
  - exact project-scoped `sentence_nlp_snapshot` row counts are too expensive
    on the huge reference project path and must not be used in an automatic UI
    refresh contract
- the practical fix therefore became:
  - add a read-only governance/reporting service for large derived artifacts
  - expose it only as an on-demand dashboard dialog, not as an automatic
    dashboard metric
  - reuse the existing snapshot readiness aggregate for snapshot volume/coverage
    instead of issuing a fresh exact snapshot row count on huge DBs

Concrete output of this wave:

- new read-only service:
  - `app/services/derived_artifact_governance_service.py`
- new on-demand operator dialog from `ProjectDashboard`:
  - `app/ui/dialogs/project_artifact_governance_dialog.py`
- new worker / dashboard wiring:
  - `app/ui/workers.py`
  - `app/ui/project_dashboard.py`
- lifecycle doc now explicitly records the online metric contract:
  - exact project counts where affordable
  - snapshot volume from readiness aggregate
  - no cleanup or retention writes from the UI surface

Evidence:

- targeted regressions:
  - `tests/test_derived_artifact_governance_service.py`
  - `tests/test_project_artifact_governance_dialog.py`
  - `tests/test_project_dashboard_governance_dialog.py`
  - result: `8 passed`
- broader adjacent regressions:
  - `tests/test_snapshot_readiness_service.py`
  - `tests/test_documents_snapshot_readiness_ui.py`
  - `tests/test_project_dashboard_metrics.py`
  - `tests/test_project_delete_flow.py`
  - `tests/test_terms_snapshot_reuse_summary.py`
  - result: `28 passed`
- live evidence on `hewiki_gpu_processing test.db`, `project_id=1`:
  - exact `sentence_nlp_snapshot` row count by naïve project join took about
    `212s`, so it was intentionally excluded from the online governance
    contract
- existing `SnapshotReadinessService.get_project_summary()` remained usable at
  about `9.5s`
- exact `lemma_doc_stat` project count remained practical but still dominated
  cold governance at about `3.3s` before the follow-up narrow patch

Remaining note:

- this patch improves operator visibility and lifecycle governability without
  reopening heavy validation
- it does not add retention cleanup yet
- the next active priority is now `PATCH-P1-02`

Implemented follow-up: per-document snapshot readiness stats

- schema `42` now persists snapshot coverage state on `source_document`:
  - `snapshot_sentence_count`
  - `snapshot_stats_state`
  - `snapshot_stats_updated_at`
- normal NLP processing and staged snapshot backfill now update those
  per-document stats transactionally
- reference CLI now provides the required companion contract:
  - `--verify-snapshot-stats`
  - `--rebuild-snapshot-stats`
  - heavy rebuild writes stay under backup/preflight/protected-db guardrails
- live evidence on `hewiki_gpu_processing test.db`, `project_id=1`:
  - cold `SnapshotReadinessService.get_project_summary()` ~= `0.505s`
  - first implementation left cold governance at ~= `3.884s` because exact
    `lemma_doc_stat` counting still dominated at ~= `3.489s`
- this means the snapshot-governance bottleneck has been structurally removed
  for the current layer; any future governance acceleration should first
  re-audit the remaining exact `lemma_*` counts

Follow-up narrow cold-governance patch:

- implemented on `2026-03-12`
- `lemma_doc_stat` governance volume is now derived from
  `SUM(lemma_project_stat.doc_freq)` instead of a cold `COUNT(*)` over the
  104M-row `lemma_doc_stat` table
- live evidence on the same `hewiki_gpu_processing test.db`, `project_id=1`:
  - cold readiness ~= `0.512s`
  - cold `lemma_*` aggregate ~= `0.112s`
  - full cold governance summary ~= `0.636s`
- this removed the last known cold-path blocker in the current governance
  layer; telemetry retention apply validation is now the completed follow-up
  evidence wave for the same operator-cost branch

Historical pre-implementation note (superseded by the schema 42 doc-stats wave):

- current governance/readiness latency is acceptable for an on-demand
  background-loaded operator dialog:
  - naïve exact project-scoped `sentence_nlp_snapshot` count on live hewiki
    scale was about `212s` and is intentionally excluded from the normal UI
    contract
  - existing `SnapshotReadinessService.get_project_summary()` remained usable at
    about `9.5s`
- later live re-audit on the approved dev/test DB exposed a much worse
  cold-tail for the first snapshot readiness query:
  - first cold `SnapshotReadinessService.get_project_summary()` on
    `project_id=1` measured about `100s`
  - warm/repeated snapshot readiness calls then fell back to about `7.4s`
  - full governance summary in the same process stayed around `11.1s` to
    `11.4s`
- therefore this branch is explicitly deferred until governance latency becomes
  a real workflow blocker
- preserve this branch as design context only:
  - do not implement it during `PATCH-P1-02`
  - re-open it only if a later decision gate promotes readiness latency from an
    acceptable operator cost to a real workflow blocker

#### Deferred PATCH-01: low-risk query/cache polish

- narrow the snapshot coverage query further
- avoid recomputing fields the current UI does not display
- continue reusing cached last-summary data where safe
- expected effect:
  - modest improvement only
  - not order-of-magnitude
  - not the preferred path for materially faster cold reads

#### Deferred PATCH-02: preferred future acceleration via per-document snapshot stats

- add doc-level snapshot coverage state either:
  - directly on `source_document`, or
  - in a dedicated doc-level stats table
- candidate fields:
  - `snapshot_sentence_count`
  - optional `snapshot_coverage_state`
  - optional `last_snapshot_updated_at`
- update that state in:
  - normal NLP processing
  - snapshot backfill merge
  - project/document delete
- rationale:
  - governance/readiness would read document-level rows instead of millions of
    snapshot rows
  - this is the preferred future path if materially faster readiness is needed
  - it is stronger than query tweaks and safer than jumping directly to a
    project-level materialized summary

#### Deferred PATCH-03: faster but riskier project-level materialized summary

- introduce a `project_artifact_stats` / `project_snapshot_stats` style table
- pros:
  - maximum read speed
- cons:
  - higher drift risk
  - more write-semantic complexity
  - requires explicit rebuild/repair support
- positioning:
  - fallback only
  - not the default recommendation

#### Deferred PATCH-04: mandatory rebuild/verify companion

If deferred PATCH-02 or PATCH-03 is ever activated, it must ship together with:

- manual rebuild of summary/stat rows
- consistency verification
- safe repair when drift is detected

Activation criteria for the deferred branch:

- governance/readiness latency becomes a real workflow blocker
- the dialog becomes frequent operator workflow instead of occasional
  diagnostics
- the current `~9.5s` cold readiness read is judged productively harmful
- there is an explicit requirement for near-interactive readiness/governance
  load time

Current recommendation:

- keep `PATCH-P1-02` ahead of this branch
- re-evaluate only after the audio cache contract work
- if this branch is later activated:
  - prefer deferred PATCH-02 first
  - carry deferred PATCH-04 with it
  - keep deferred PATCH-03 only as a higher-risk fallback

### PATCH-P1-02: Finish audio cache contract

Goal:

- finish the move from weak uniqueness to a content-addressed `audio_asset`
  cache contract.

Primary files:

- `app/infra/sa_models.py`
- `app/services/audio_generation_service.py`
- `docs/PROJECT_DATA_CACHE_LIFECYCLE_CONTRACT.md`

## Controllability principles for the next wave

1. Prefer bounded phases over monolithic long-running write windows.
2. Separate "expensive but inevitable" from "poorly governed and fixable".
3. Do not reopen heavy snapshot validation unless the decision gate is
   explicitly triggered.
4. Add evidence and logging for stage/cancel/lock behavior before broadening
   scope.
5. Protect the main install DB from write-risk until runtime safeguards, not
   only docs, are in place.

Status after implementation wave:

- implemented on `2026-03-11`
- refined by evidence:
  - canonical persisted audio row identity is now `(lang, input_hash)` for
    hashed rows
  - legacy weak lookup is retained only as a bounded compatibility fallback for
    hash-less rows
  - regenerated identical requests still update the same canonical row, while
    changed spoken payloads can coexist as separate cache rows

Concrete output of this wave:

- new migration:
  - `app/infra/migrations/041_audio_asset_content_addressed_identity.sql`
- updated row identity/runtime services:
  - `app/infra/sa_models.py`
  - `app/services/audio_asset_service.py`
  - `app/services/audio_generation_service.py`
  - `app/ui/widgets/audio_player_panel.py`

Evidence:

- targeted regressions:
  - `tests/test_audio_asset_content_addressed_migration.py`
  - `tests/test_audio_generation_service.py`
  - `tests/test_audio_generation_with_pronunciation.py`
  - `tests/test_audio_playback_service.py`
  - `tests/test_audio_provider_chain_fallback.py`
  - `tests/test_audio_generation_budget_guards.py`
  - `tests/test_audio_regenerate_provider_switch_latest_ready.py`
  - `tests/test_user_dictionaries_audio_stub.py`
  - result: `22 passed`
- broader adjacent regressions:
  - `tests/test_audio_queue_populate_worker.py`
  - `tests/test_audio_queue_display_resolver.py`
  - `tests/test_audio_player_playlist_display_refresh.py`
  - `tests/test_audio_track_source_url.py`
  - `tests/test_user_dictionaries_service.py`
  - `tests/test_sentences_workspace_service.py`
  - result: `75 passed`

## Immediate execution order

1. no active operator write slice remains open on this branch
2. future heavy validation only by explicit decision gate

### PATCH-P1-03: Telemetry-first retention for `processor_run` / `run_error`

Goal:

- add an explicit retention/cleanup contract for project-scoped processing
  telemetry without touching heavier derived tables first
- make the operational cleanup path safe, previewable, and evidence-preserving

Primary files:

- `app/services/project_telemetry_retention_service.py`
- `scripts/prune_project_telemetry.py`
- `tests/test_project_telemetry_retention_service.py`
- `tests/test_prune_project_telemetry_cli.py`
- docs/runbooks

Expected output:

- dry-run by default for telemetry cleanup
- explicit apply gate
- bounded keep-policy for old successful rows
- preserve:
  - recent successful rows
  - all non-ok rows
  - successful rows that still carry explicit note/evidence metadata

Status after implementation wave:

- implemented on `2026-03-11`
- refined by live evidence on the approved hewiki dev/test DB:
  - `processor_run` growth is the first safe cleanup target
  - on `project_id=1`:
    - `processor_run = 387,613`
    - `run_error = 15`
    - `ok = 387,598`
    - almost all growth sits in old successful rows
- this made it possible to start with telemetry-first retention without
  touching `lemma_doc_stat`, `lemma_project_stat`, or `sentence_nlp_snapshot`

Concrete output of this wave:

- new service:
  - `app/services/project_telemetry_retention_service.py`
- new CLI:
  - `scripts/prune_project_telemetry.py`
- runtime contract:
  - dry-run is default
  - `--preflight-only` requires `--backup-db-path`
  - `--apply` requires both `--backup-db-path` and `--confirm-project-id`
  - the protected baseline/main reference DB stays blocked unless
    `--allow-protected-db-telemetry-apply` is passed explicitly
  - only successful rows with empty note metadata are prunable
  - noted/evidence rows and all non-ok rows are preserved
  - no automatic `VACUUM`

Evidence:

- targeted regressions:
  - `tests/test_project_telemetry_retention_service.py`
  - `tests/test_prune_project_telemetry_cli.py`
  - result: `10 passed`
- live dry-run on `hewiki_gpu_processing test.db`, `project_id=1`:
  - artifact: `build/logs/telemetry_retention/project1_prune_dry_run.json`
  - with `keep_latest_ok = 200`:
    - `prunable_ok_runs = 387,398`
    - `prunable_run_error_rows = 0`
    - preserved rows remain:
      - `200` recent successful rows
      - `3` noted/evidence successful rows
      - `15` non-ok rows
- live preflight on the same DB with explicit backup path:
  - artifact: `build/logs/telemetry_retention/project1_prune_preflight.json`
  - result:
    - `operation_mode = preflight_only`
    - target probe ok on schema `42`
    - backup probe ok on schema `41`
    - `protected_target = false`
    - `prunable_ok_runs = 387,398`
- live `--apply` validation on `2026-03-12` using a disposable clone of the
  same DB:
  - artifact: `build/logs/telemetry_retention/project1_apply_validation_summary.json`
  - result:
    - before apply: `387,613` total runs, `387,598` ok, `15` non-ok, `3`
      noted/evidence ok rows, `387,398` prunable ok rows
    - apply deleted exactly `387,398` ok rows in about `5.388s`
    - after apply: `215` total runs, `200` ok, `15` non-ok, `3`
      noted/evidence ok rows, `0` prunable ok rows
    - `run_error` stayed at `15`
    - file size stayed unchanged until explicit `VACUUM`, as designed
    - source `hewiki_gpu_processing test.db` stayed untouched
- housekeeping on `2026-03-12`:
  - disposable clone `build\bench\hewiki_telemetry_apply_validation_20260312.db`
    was deleted after validation closed
  - checked sidecars:
    - `.db-wal` -> not present
    - `.db-shm` -> not present
    - `.db-journal` -> not present
  - source DB, backup DB, JSON evidence, and docs evidence were preserved

Remaining note:

- this wave only governs operational telemetry growth
- it does not turn the remaining large derived artifacts into age-prune
  candidates
- the follow-up governance contract is now:
  - `processor_run`
    - maintenance mode: `retention_available`
    - actionable via dry-run/apply CLI
  - `run_error`
    - maintenance mode: `retention_with_parent_runs`
    - only cleaned indirectly through parent `processor_run` retention
  - `lemma_doc_stat`
  - `lemma_project_stat`
  - `sentence_nlp_snapshot`
    - maintenance mode: `reset_rebuild_only`
    - not eligible for age-based retention
    - operator guidance should point to explicit reset/rebuild workflows instead
      of incremental pruning
    - reference-scale rebuild path is now preserved via
      `scripts/process_reference_corpus.py --project-id <id> --reprocess-all`
    - reference CLI preamble now skips expensive snapshot-audit queries unless
      `--backfill-snapshots` or `--coverage-only` is explicitly requested
- governance UI now surfaces those maintenance modes explicitly, including a
  safe telemetry dry-run CLI copy path, a reference rebuild dry-run CLI copy
  path, a telemetry preflight CLI hint, and a backup-backed rebuild preflight
  template, while staying observational-only
- heavy reference rebuild execution is now also aligned with the safety gate:
  actual `--reprocess-all` writes require backup/preflight readiness and use the
  same protected-target override gate as heavy snapshot-backfill writes

Decision update:

- telemetry retention apply validation is complete on a disposable clone
- disposable clone housekeeping is complete; no disposable validation DB remains
- no automatic write follow-up is queued from this layer
- the next active layer is decision-gate triage only, not a reopened write branch
- future heavy validation remains an explicit decision-gate item only

## Cold-Audit Framework Handoff

The canonical repository-wide cold-audit framework now lives in:

- `docs/COLD_AUDIT_FRAMEWORK.md`

Use that document for:

- cold terminology (`cold-path`, `cold governance`, `cold breakdown`,
  `cold-tail`, `decision gate`, `evidence-first patch`);
- Levels 1-10 cold-audit research scope;
- A-G research matrix;
- prioritization (`P0`/`P1`/`P2`/`P3`, blocker vs residual tail vs deferred);
- repo contract for evidence naming, closure markers, and decision-gate usage.

Roadmap role after this handoff:

- keep current-layer status and next-layer priority here;
- do not duplicate the full framework here;
- do not reopen closed governance/readiness/telemetry branches without a new
  evidence gate framed through the canonical cold-audit doc.

## First framework-driven cold-audit wave

The first official task-specific use of the canonical framework is now recorded in:

- `docs/STARTUP_DB_OPEN_COLD_AUDIT_2026-03-12.md`

Wave outcome:

- bounded startup `db_open` probe on the repo-local `hdle_premium.db` measured
  `82 ms` first probe and `66 ms` repeat probe;
- the probe isolates DB-open only and does not claim full UI first-usable-state;
- startup defer behavior for huge legacy `SETTINGS` DBs remains aligned across
  code, docs, and tests;
- no startup patch branch is opened from this wave.

Current status after the wave:

- startup DB-open triage on the local repo target is closed;
- next startup-related layer is decision-gate triage only;
- do not reopen a startup branch without new Level 7 UI evidence,
  approved reference-scale startup evidence, or degraded-path drift evidence.

## Second framework-driven cold-audit wave

The second official task-specific use of the canonical framework is now recorded in:

- `docs/DOCUMENT_PICKER_COLD_AUDIT_2026-03-12.md`

Wave outcome:

- current approved-target picker evidence on
  `hewiki_gpu_processing test.db` shows:
  - `picker_page_empty p95 ~= 0.152s`
  - `picker_page_search p95 ~= 0.120s`
- the picker still has structural query-plan residue, including TEMP B-TREE use,
  but it is no longer a current blocker;
- staged first-paint behavior remains intact by code and targeted regression
  coverage;
- no picker patch branch is reopened from this wave.

Current status after the wave:

- picker cold-audit triage is closed;
- picker remains historical optimization context, not an active branch;
- do not reopen picker work without a new approved-target breach, real UI
  first-usable-state regression, or fallback-drift evidence.

## Third framework-driven cold-audit wave

The third official task-specific use of the canonical framework is now recorded in:

- `docs/SENTENCES_WORKSPACE_COLD_AUDIT_2026-03-12.md`
- `docs/SENTENCES_WORKSPACE_REPAIR_2026-03-12.md`
- `docs/SENTENCES_FILTERED_SEARCH_DECISION_2026-03-12.md`

Wave outcome:

- strict read-only evidence on the approved hewiki test DB shows:
  - Sentences first page ~= `3.56s` to `4.10s`
  - Sentences unfiltered total count ~= `0.016s` to `0.024s`
  - Sentences filtered count with `text_search='wiki'` ~= `8.31s` to `8.72s`
- the dominant current blocker is the Sentences page query itself:
  - current breakdown shows `page_query ~= 3.68s`
  - current query plan still uses `USE TEMP B-TREE FOR ORDER BY`
- staged first-paint and anti-stale request handling are still correct, but they
  do not remove the blocker because rows arrive only after the slow stage-1 page
  query completes.

Repair outcome:

- the bounded Sentences repair was implemented in `app/services/sentences_workspace_service.py`
  without changing the staged UI contract;
- approved-target strict read-only evidence now shows:
  - Sentences unfiltered first page ~= `0.219s`
  - Sentences unfiltered count ~= `0.021s`
  - Sentences filtered first page with `text_search='wiki'` ~= `2.182s`
  - Sentences filtered exact count with `text_search='wiki'` ~= `7.889s`
- the repaired page-query plan no longer shows the old temp-sort pattern:
  - current fast page plan = `SCAN document_sentence`
- after-breakdown shows the old dominant blocker is gone:
  - default `page_rows ~= 0.002s`
  - default `audio ~= 0.195s`
  - filtered `page_rows ~= 1.852s`
  - filtered `count ~= 7.592s`

Current status after repair:

- the Sentences P0 first-page blocker is operationally closed;
- the remaining filtered search/count tail is explicitly decision-gated, not an
  automatic follow-up branch;
- the filtered search decision note currently classifies that residual tail as
  `P1`, not blocker, because:
  - filtered first page is secondary and no longer the default user-visible blocker;
  - exact filtered count remains async stage-2 work;
  - `sentence_fts` is not healthy enough on the approved target for a bounded
    FTS-backed follow-up patch;
- the next active work returns to the canonical cold-audit framework for the
  next narrow subsystem wave;
- keep startup, picker, governance/readiness, telemetry, and heavy-validation
  branches closed unless their own future evidence gates are crossed.

## Fourth framework-driven cold-audit wave

The fourth official task-specific use of the canonical framework is now
recorded in:

- `docs/DICTIONARY_COLD_AUDIT_2026-03-12.md`

Wave outcome:

- strict read-only evidence on the approved hewiki test DB shows:
  - Dictionary default first page ~= `0.003s`
  - Dictionary exact count (cold) ~= `0.129s`
  - Dictionary exact count (cached) ~= `0.000s`
- the default Dictionary cold path is therefore not a blocker;
- Dictionary staged first-paint and deferred exact-count behavior remain intact
  by code and targeted regression coverage.

Approved-target search/parity outcome:

- `lemma_fts` exists, but current approved-target parity is not healthy:
  - `lemma` rows = `2,071,947`
  - `lemma_fts` rows = `2,076,909`
  - extra `lemma_fts` rows = `4,962`
- in the recorded 12-term approved-target parity sample:
  - `LIKE` count was non-zero for `12 / 12` terms;
  - service search count was non-zero for `0 / 12` terms;
  - `lemma_id IN (SELECT rowid FROM lemma_fts MATCH ...)` was non-zero for
    `0 / 12` terms.

Current status after the wave:

- Dictionary default cold-path triage is closed;
- no Dictionary performance patch branch is opened from this wave;
- Dictionary search/FTS health is a separate `P1` decision-gated topic, not an
  automatically active branch;
- the next active work returns to the canonical cold-audit framework for the
  next narrow subsystem wave;
- do not reopen Dictionary work without new approved-target evidence and an
  explicit search/FTS health gate.

## Fifth framework-driven cold-audit wave

The fifth official task-specific use of the canonical framework is now
recorded in:

- `docs/TERMS_COLD_AUDIT_2026-03-12.md`

Wave outcome:

- strict read-only evidence on the approved hewiki test DB shows:
  - Terms default first page ~= `0.003s` first run and `0.056s` repeat probe
  - Terms default exact count ~= `0.009s` first run and `0.002s` repeat probe
  - Terms representative search page ~= `0.001s` first run and `0.003s` repeat
    probe
  - Terms representative search exact count ~= `0.001s`
- the current Terms subsystem is therefore not a cold blocker on the approved
  target.

Current status after the wave:

- Terms cold-path triage is closed;
- no Terms runtime patch branch is opened from this wave;
- the historical perf note that described Terms as count-before-emit is now
  explicitly treated as historical context only, not current canonical
  behavior;
- the next active work returns to the canonical cold-audit framework for the
  next narrow subsystem wave;
- do not reopen Terms work without new approved-target evidence.

## Sixth framework-driven cold-audit wave

The sixth official task-specific use of the canonical framework is now
recorded in:

- `docs/CONCORDANCE_COLD_AUDIT_2026-03-12.md`

Wave outcome:

- strict read-only approved-target evidence shows that Concordance is currently
  blocked by prerequisite `sentence_fts` health rather than by a measured cold
  latency offender:
  - `sentence_fts` rows = `1,792`
  - project-scoped sentence rows for project `1` = `13,387,588`
  - project-joined `sentence_fts` rows = `0`
- a bounded raw project-scoped Concordance FTS probe therefore returns no rows
  quickly, but that is not evidence of a healthy or optimized search surface.

Current status after the wave:

- Concordance cold-audit triage is closed;
- no Concordance runtime patch branch is opened from this wave;
- Concordance is now explicitly treated as a `sentence_fts` dependency-health
  gate, not as an isolated latency branch;
- the next active work returns to the canonical cold-audit framework for the
  next narrow subsystem wave;
- do not reopen Concordance work without a separate approved-target
  `sentence_fts` health gate.

## Seventh framework-driven cold-audit wave

The seventh official task-specific use of the canonical framework is now
recorded in:

- `docs/TM_PANEL_COLD_AUDIT_2026-03-12.md`
- `docs/TM_PANEL_REPAIR_2026-03-13.md`
- `docs/TM_PANEL_COUNT_TAIL_DECISION_2026-03-13.md`

Wave outcome:

- strict read-only approved-target evidence shows that the current TM panel
  default page query is already healthy after migration `030`, but first usable
  state is still blocked by exact count:
  - default page runs: `0.050s` to `0.137s`
  - default exact count runs: `7.545s` to `10.490s`
  - default rows-gate runs: `7.594s` to `10.628s`
- representative search shows the same dominant layer rather than a separate
  first fix:
  - search page runs: `0.706s` to `0.814s`
  - search exact count runs: `8.502s` to `8.733s`
  - search rows-gate runs: `9.208s` to `9.450s`
- query-plan evidence confirms that:
  - default page uses `idx_tm_entry_proj_updated_at(project_id, updated_at DESC)`
  - count paths still spend seconds-scale time on exact total evaluation over
    the project-scoped TM slice

Current status after the wave:

- TM panel cold-audit evidence gate was crossed and the bounded repair was opened;
- the TM panel P0 first-paint blocker is now operationally closed:
  - rows are no longer held behind exact count
  - default page-ready state now matches the already-healthy page query layer
- the remaining exact-count/search tail is explicitly decision-gated:
  - default exact total still completes at `7.594s` to `10.628s`
  - representative search exact total still completes at `9.208s` to `9.450s`
- the follow-up decision note currently classifies that residual tail as `P1`,
  not blocker, because:
  - rows already render at the healthy page-ready layer;
  - exact total is now stage-2 UX completeness work rather than first render;
  - any further improvement would mix performance work with count semantics
    decisions, not just a narrow read-path fix;
- no immediate second TM patch is opened from this repair;
- the next active work returns to the canonical cold-audit framework for the
  next narrow subsystem wave;
- do not widen TM work into a broad search redesign or TM write-path refactor
  without new evidence;
- startup, picker, Sentences filtered-tail, Dictionary, Terms, and Concordance
  cold-audit branches remain closed unless their own gates are crossed again.

## Eighth framework-driven cold-audit wave

The eighth official task-specific use of the canonical framework is now
recorded in:

- `docs/COVERAGE_PANEL_COLD_AUDIT_2026-03-13.md`
- `docs/COVERAGE_PANEL_REPAIR_2026-03-13.md`

Wave outcome:

- strict read-only approved-target evidence shows that the current Coverage
  panel is blocked by lemma coverage exact-count work on the large project
  lemma slice, not by cluster coverage or untranslated-list loading:
  - `lemma` rows for `project_id=1`: `2,071,947`
  - lemma total count runs in `0.073s`
  - term-cluster coverage runs in `0.068s`
  - untranslated lemmas top `100` runs in `0.185s`
  - untranslated term clusters top `100` runs in `0.068s`
  - raw exact covered-lemma count did not complete within `120s`
  - full read-only service probe did not complete within `600s`
- current query-plan evidence confirms the hot layer:
  - `USE TEMP B-TREE FOR count(DISTINCT)`
  - `SEARCH l USING COVERING INDEX idx_lemma_project_text (project_id=?)`
  - `SEARCH t USING INDEX idx_tm_entry_lookup ... LEFT-JOIN`
- the current UI/worker contract makes the blocker user-visible:
  - `CoveragePanel` auto-loads on open
  - `CoverageWorker` executes lemma coverage first
  - one terminal `results_ready(dict)` payload is emitted only after all four
    coverage steps complete
  - the panel therefore has no staged first usable state today

Current status after the wave:

- Coverage panel cold-audit evidence gate was crossed and the bounded repair was opened;
- the Coverage panel `P0` first-usable-state blocker is now operationally closed:
  - cluster coverage and untranslated lists render before lemma coverage
  - stage-1 partial-ready state now arrives in `0.391s`
  - the panel no longer waits for terminal `results_ready(dict)` before showing
    useful state
- the remaining residual tail is explicitly decision-gated:
  - exact lemma coverage total still uses the old `COUNT(DISTINCT)` + join path
  - query shape was intentionally unchanged in this repair
  - the residual tail is now stage-2 completeness work rather than panel-open
    gating work
- no immediate second Coverage patch is opened from this repair;
- the next active work returns to the canonical cold-audit framework for the
  next narrow subsystem wave;
- do not widen this into general metrics redesign, historical P2 docs cleanup,
  or TM/search work without a new evidence gate;
- startup, picker, Sentences filtered-tail, Dictionary, Terms, Concordance, and
  TM residual-tail branches remain closed unless their own gates are crossed
  again.

## Ninth framework-driven cold-audit wave

The ninth official task-specific use of the canonical framework is now
recorded in:

- `docs/AUDIO_ADD_ALL_DIALOG_COLD_AUDIT_2026-03-13.md`
- `docs/AUDIO_ADD_ALL_DIALOG_REPAIR_2026-03-13.md`

Wave outcome:

- strict read-only approved-target evidence shows that the main Audio Player
  dock is not the blocker, but the Add-All dialog cold open path is:
  - queue rows: `0`
  - history rows: `0`
  - playlists: `1`
  - project list load: `0.019s`
  - `project_id=1` processed-doc query: `0.818s`
  - `project_id=1` exact sentence estimate: `18.499s`
  - offscreen dialog init: `48.989s`
- approved-target row volume explains the blocker:
  - `project_id=1` processed docs: `387,639`
  - `project_id=1` sentence estimate: `13,387,588`
- query-plan evidence confirms the hot layers:
  - document list still uses `USE TEMP B-TREE FOR ORDER BY`
  - exact estimate walks the project-scoped sentence slice via
    `idx_sentence_doc`
- the current dialog contract makes the blocker user-visible:
  - projects load on dialog init
  - the default `sentence` kind immediately loads the full processed-doc list
  - one `QListWidgetItem` is materialized per document
  - the exact sentence estimate also runs before the dialog becomes useful

Current status after the wave:

- Audio Add-All dialog cold-audit evidence gate was crossed and the bounded
  repair was opened;
- the Audio Add-All dialog `P0` blocker is now operationally closed:
  - strict read-only offscreen dialog init is now `0.238s`;
  - the dialog no longer eagerly materializes the `387,639`-row processed-doc list;
  - open-time sentence estimate is now an approximate planning value and runs in `0.032s`;
  - representative processed-document search is now on-demand and staged:
    - first page (`wiki`): `0.226s`
    - total count (`wiki`): `0.110s`
- queue population semantics remain exact after dialog acceptance;
- no immediate residual Audio branch is opened from this repair;
- the next active work returns to the canonical cold-audit framework for the
  next narrow subsystem wave;
- do not reopen startup, picker, Sentences filtered-tail, Dictionary, Terms,
  Concordance, TM residual-tail, Coverage residual-tail, or Audio Add-All
  work without new evidence gates.

## Tenth framework-driven cold-audit wave

The tenth official task-specific use of the canonical framework is now
recorded in:

- `docs/DOCUMENTS_VIEW_COLD_AUDIT_2026-03-13.md`
- `docs/DOCUMENTS_VIEW_REPAIR_2026-03-13.md`

Wave outcome:

- strict read-only approved-target evidence shows that `ProjectDashboard` is
  not the next bottleneck:
  - `ProjectDashboard` open: `0.166s`
- the next justified surface is `DocumentsView`, and the current blocker is not
  the async documents page or snapshot readiness workers:
  - full `DocumentsView` cold open: `2.300s`
  - same path without NLP engine checks: `0.063s`
  - isolated engine-check delta: `2.237s`
  - after async worker completion the first page reaches:
    - `25` rows
    - `387,639` total documents
- current runtime evidence localizes the blocking layer:
  - `stanza` import: `2.298s`
  - fresh-process `torch` import: `1.685s`
  - `torch.cuda.is_available()`: effectively `0.000s`
- the current Documents open contract makes the blocker user-visible:
  - `DocumentsView.init_ui()` performs synchronous NLP engine capability checks
    in the UI thread before starting background loading
  - only after those checks do `load_corpus()`, `DocumentsPageWorker`, and
    `SnapshotReadinessWorker` proceed

Current status after the wave:

- Documents view cold-audit evidence gate was crossed and the bounded repair
  was opened;
- the Documents view `P0` blocker is now operationally closed:
  - `DocumentsView` init now returns in `0.077s`;
  - first page now arrives in `0.376s`;
  - NLP engine readiness completes later at `2.045s`;
  - the view opens usable while the engine label stays in
    `Checking NLP engine readiness...` state;
  - after background completion the first page still reaches:
    - `25` rows
    - `387,639` total documents;
- the repaired contract keeps the right scope boundaries:
  - async documents paging remains intact;
  - snapshot readiness remains async and unchanged;
  - process/re-process buttons stay disabled only until readiness is known;
- approved-target after evidence still records `db_mtime_unchanged=true`;
- no immediate residual Documents branch is opened from this repair;
- the next active work returns to the canonical cold-audit framework for the
  next narrow subsystem wave;
- do not reopen startup, picker, Sentences filtered-tail, Dictionary, Terms,
  Concordance, TM residual-tail, Coverage residual-tail, Audio Add-All, or
  generic Documents work without new evidence gates.

## Eleventh framework-driven cold-audit wave

The eleventh official task-specific use of the canonical framework is now
recorded in:

- `docs/PROJECT_VIEW_COLD_AUDIT_2026-03-13.md`
- `docs/PROJECT_VIEW_REPAIR_2026-03-13.md`

Wave outcome:

- strict read-only approved-target evidence shows that the next justified
  surface is the real project-open workflow, not another isolated tab:
  - full `ProjectView` cold open: `1.627s`
  - shell-only `ProjectView` with all tabs stubbed: `0.071s`
- child-localization evidence shows that the visible default tab is no longer
  the blocker:
  - `ProjectView` with only `DocumentsView` real: `0.089s`
  - `ProjectView` with only `UserDictionariesView` real: `0.087s`
- the dominant current open-time layer is a hidden child tab:
  - `ProjectView` with only `TermCardView` real: `1.593s`
  - standalone `TermCardView` cold open: `1.553s`
  - `TermCardView` queue rows on open: `760`
- the current project-open contract makes the blocker user-visible:
  - `ProjectView` returns on the `Documents` tab
  - but `TermCardView.load_review_queue()` still runs synchronously during
    `ProjectView.init_ui()`
  - the open-project workflow is therefore paying almost entirely for hidden
    `Term Cards` work

Current status after the wave:

- ProjectView cold-audit evidence gate was crossed and the bounded repair was
  opened;
- the ProjectView `P0` blocker is now operationally closed:
  - full `ProjectView` cold open is now `0.442s`;
  - the visible tab on open remains `Documents`;
  - hidden `Term Cards` no longer load on open:
    - `term_cards_loaded_on_open = false`
    - status on open: `Review queue loads when tab is opened`;
  - first explicit `Term Cards` activation now takes `1.197s`;
  - the queue still reaches `760` rows after activation;
- the repaired contract keeps the right scope boundaries:
  - no broad lazy-tab framework was introduced;
  - `Documents` stays the visible default tab;
  - hidden `Term Cards` load only when the tab is actually opened;
- approved-target after evidence still records `db_mtime_unchanged=true`;
- no immediate residual ProjectView branch is opened from this repair;
- the next active work returns to the canonical cold-audit framework for the
  next narrow subsystem wave;
- do not reopen startup, picker, Sentences filtered-tail, Dictionary, Terms,
  Concordance, TM residual-tail, Coverage residual-tail, Audio Add-All,
  generic Documents work, or ProjectView without new evidence gates.

## Twelfth framework-driven cold-audit wave

The twelfth official task-specific use of the canonical framework is now
recorded in:

- `docs/TERM_CARDS_COLD_AUDIT_2026-03-13.md`

Wave outcome:

- strict read-only approved-target evidence shows that the next visible
  candidate after the `ProjectView` repair is standalone `Term Cards`
  activation:
  - standalone `TermCardView` cold open: `1.043s`
  - queue rows after init: `760`
- the current cold path is not a raw queue SQL problem:
  - raw `term_cluster` queue query: `0.011s`
  - queue plan: `SEARCH term_cluster USING INDEX idx_cluster_freq (project_id=?)`
  - exact queue count: `0.001s`
- the dominant current layer is synchronous enrichment:
  - `TermCardService.list_review_queue()`: `0.330s`
  - `resolve_cross_view_status()`: `0.606s`
  - `resolve_pronunciation_overlay()`: `0.002s`
- the current `Term Cards` contract still blocks first usable state on full
  queue enrichment:
  - there is no staged rows-first / overlays-later contract today;
  - queue SQL and exact count are already cheap, so a future bounded repair
    would likely target UI/service staging rather than indexing

Current status after the wave:

- standalone `Term Cards` is now formally classified from current evidence;
- current classification is:
  - `blocker = no`
  - `priority = P1`
- no immediate `Term Cards` repair branch is opened from this wave;
- the next active work returns to the canonical cold-audit framework for the
  next narrow subsystem wave;
- do not reopen startup, picker, Sentences filtered-tail, Dictionary, Terms,
  Concordance, TM residual-tail, Coverage residual-tail, Audio Add-All,
  generic Documents work, ProjectView, or standalone `Term Cards` without new
  evidence gates.

## Thirteenth framework-driven cold-audit wave

The thirteenth official task-specific use of the canonical framework is now
recorded in:

- `docs/VERIFICATION_PANEL_COLD_AUDIT_2026-03-13.md`

Wave outcome:

- a bounded candidate sweep across remaining untriaged surfaces kept
  `VerificationPanel` as the next largest visible candidate:
  - `verification_panel`: `0.219s`
  - `user_dictionaries_view`: `0.198s`
  - `database_switch_dialog`: `0.128s`
  - `provider_settings_dialog`: `0.119s`
  - `resources_manager_dialog`: `0.035s`
  - `import_wizard`: `0.007s`
- strict read-only approved-target evidence then localized the panel contract:
  - full `VerificationPanel` cold open: `0.244s`
  - `load_db_path()`: `0.000s`
  - `load_projects()`: `0.001s`
  - `dict_project` rows on target: `4`
  - project combo items after init: `5`
- the panel keeps heavy work off the cold-open path:
  - `P1VerificationWorker` is not started on open;
  - cold-open work is just layout + DB-path label + project combo population

Current status after the wave:

- `VerificationPanel` is now formally classified from current evidence;
- current classification is:
  - `blocker = no`
  - `priority = P3`
- no immediate `VerificationPanel` repair branch is opened from this wave;
- the next active work returns to the canonical cold-audit framework for the
  next narrow subsystem wave;
- do not reopen startup, picker, Sentences filtered-tail, Dictionary, Terms,
  Concordance, TM residual-tail, Coverage residual-tail, Audio Add-All,
  generic Documents work, ProjectView, standalone `Term Cards`, or
  `VerificationPanel` without new evidence gates.

## Fourteenth framework-driven cold-audit wave

The fourteenth official task-specific use of the canonical framework is now
recorded in:

- `docs/USER_DICTIONARIES_COLD_AUDIT_2026-03-13.md`

Wave outcome:

- the bounded candidate sweep already kept `UserDictionariesView` as the next
  visible candidate after `VerificationPanel`:
  - `user_dictionaries_view`: `0.198s`
- strict read-only approved-target evidence then confirmed the actual contract:
  - full `UserDictionariesView(project_id=1)` init: `0.058s`
  - first page ready: `0.164s`
  - `list_dictionaries()`: `0.043s`
  - `query_items()`: `0.053s`
  - `get_dictionary_review_summary()`: `0.002s`
- dataset-tier evidence also stayed tiny:
  - dictionaries on target: `1`
  - total `user_dictionary_item` rows: `18`
  - explicit project-scope replay remained identical:
    - project-scope first page total: `18`

Current status after the wave:

- `UserDictionariesView` is now formally classified from current evidence;
- current classification is:
  - `blocker = no`
  - `priority = P3`
- no immediate `UserDictionariesView` repair branch is opened from this wave;
- the approved target is not scale-viable for a major user-dictionary cold-path
  claim;
- the next active work returns to the canonical cold-audit framework for the
  next narrow subsystem wave;
- do not reopen startup, picker, Sentences filtered-tail, Dictionary, Terms,
  Concordance, TM residual-tail, Coverage residual-tail, Audio Add-All,
  generic Documents work, ProjectView, standalone `Term Cards`,
  `VerificationPanel`, or `UserDictionariesView` without new evidence gates.

## Fifteenth framework-driven cold-audit wave

The fifteenth official task-specific use of the canonical framework is now
recorded in:

- `docs/DATABASE_SWITCH_DIALOG_COLD_AUDIT_2026-03-13.md`

Wave outcome:

- the bounded candidate sweep already kept `DatabaseSwitchDialog` as the next
  largest remaining visible candidate:
  - `database_switch_dialog`: `0.128s`
- strict read-only dedicated evidence then confirmed the actual contract:
  - `inspect_db_path(current_db_path)`: `0.009s`
  - `inspect_db_path(default_db_path)`: `0.014s`
  - full `DatabaseSwitchDialog` init: `0.033s`
- metadata context stayed bounded:
  - current profile: `Custom`
  - current schema: `42`
  - default DB exists: `true`
  - default DB schema: `26`
  - baseline quick-pick available: `true`

Current status after the wave:

- `DatabaseSwitchDialog` is now formally classified from current evidence;
- current classification is:
  - `blocker = no`
  - `priority = P3`
- no immediate `DatabaseSwitchDialog` repair branch is opened from this wave;
- metadata inspection remains bounded and does not justify runtime work;
- the next active work returns to the canonical cold-audit framework for the
  next narrow subsystem wave;
- do not reopen startup, picker, Sentences filtered-tail, Dictionary, Terms,
  Concordance, TM residual-tail, Coverage residual-tail, Audio Add-All,
  generic Documents work, ProjectView, standalone `Term Cards`,
  `VerificationPanel`, `UserDictionariesView`, or `DatabaseSwitchDialog`
  without new evidence gates.

## Sixteenth framework-driven cold-audit wave

The sixteenth official task-specific use of the canonical framework is now
recorded in:

- `docs/PROVIDER_SETTINGS_DIALOG_COLD_AUDIT_2026-03-13.md`

Wave outcome:

- the bounded candidate sweep already kept `ProviderSettingsDialog` as the next
  remaining visible candidate:
  - `provider_settings_dialog`: `0.119s`
- strict read-only dedicated evidence then confirmed the actual contract:
  - full `ProviderSettingsDialog` init: `0.117s`
  - chain rows after init: `7`
  - master enabled state: `true`
- current settings also exposed a separate dependency-health issue:
  - auth mode: `service_account_json`
  - configured credential ID:
    - `mt_provider:google_cloud_translate:service_account_json`
  - open-time warning:
    - `Failed to get credential ... Failed to decrypt credential: Decryption failed: authentication tag invalid (data corrupted or tampered)`
  - preview fallback text:
    - `No Service Account JSON configured`

Current status after the wave:

- `ProviderSettingsDialog` is now formally classified from current evidence;
- current classification is:
  - `blocker = no`
  - `priority = P3`
- no immediate `ProviderSettingsDialog` cold-open repair branch is opened from
  this wave;
- the decrypt warning is tracked as a separate credential-health gate, not as a
  cold-latency branch;
- the next active work returns to the canonical cold-audit framework for the
  next narrow subsystem wave;
- do not reopen startup, picker, Sentences filtered-tail, Dictionary, Terms,
  Concordance, TM residual-tail, Coverage residual-tail, Audio Add-All,
  generic Documents work, ProjectView, standalone `Term Cards`,
  `VerificationPanel`, `UserDictionariesView`, `DatabaseSwitchDialog`, or
  `ProviderSettingsDialog` without new evidence gates.

## Seventeenth framework-driven cold-audit wave

The seventeenth official task-specific use of the canonical framework is now
recorded in:

- `docs/RESOURCES_MANAGER_DIALOG_COLD_AUDIT_2026-03-13.md`

Wave outcome:

- the bounded candidate sweep already kept `ResourcesManagerDialog` as the next
  remaining visible candidate:
  - `resources_manager_dialog`: `0.035s`
- dedicated current-state evidence then confirmed the actual contract:
  - full `ResourcesManagerDialog` init: `0.025s`
  - table rows after open: `3`
  - `ResourceRegistry.list_entries()`: `0.010s`
  - each `get_status()` stayed at `0.001s`
- current resource state stayed bounded:
  - installed required resources: `2`
  - missing optional baseline bundle: `1`
    - `hewiki_baseline_processed_bundle`

Current status after the wave:

- `ResourcesManagerDialog` is now formally classified from current evidence;
- current classification is:
  - `blocker = no`
  - `priority = P3`
- no immediate `ResourcesManagerDialog` repair branch is opened from this wave;
- the only missing row is an optional baseline bundle, not an open-time
  blocker;
- the next active work returns to the canonical cold-audit framework for the
  next narrow subsystem wave;
- do not reopen startup, picker, Sentences filtered-tail, Dictionary, Terms,
  Concordance, TM residual-tail, Coverage residual-tail, Audio Add-All,
  generic Documents work, ProjectView, standalone `Term Cards`,
  `VerificationPanel`, `UserDictionariesView`, `DatabaseSwitchDialog`,
  `ProviderSettingsDialog`, or `ResourcesManagerDialog` without new evidence
  gates.

## Eighteenth framework-driven cold-audit wave

The eighteenth official task-specific use of the canonical framework is now
recorded in:

- `docs/IMPORT_WIZARD_COLD_AUDIT_2026-03-13.md`

Wave outcome:

- the bounded candidate sweep had only one remaining visible candidate:
  - `import_wizard`: `0.007s`
- strict read-only dedicated evidence then confirmed the actual contract:
  - `ProjectService.list_projects()`: `0.043s`
  - project count on target: `4`
  - full `ImportWizard` init: `0.006s`
  - `project_combo` count after open: `4`
- current open state remained fully idle and usable:
  - `Run Import` enabled: `true`
  - `Cancel` enabled: `false`
  - no worker or file parsing begins on open

Current status after the wave:

- `ImportWizard` is now formally classified from current evidence;
- current classification is:
  - `blocker = no`
  - `priority = P3`
- no immediate `ImportWizard` repair branch is opened from this wave;
- the original bounded visible candidate sweep is now fully exhausted;
- the next active work returns to the canonical cold-audit framework for the
  next narrow subsystem wave or a new bounded candidate sweep;
- do not reopen startup, picker, Sentences filtered-tail, Dictionary, Terms,
  Concordance, TM residual-tail, Coverage residual-tail, Audio Add-All,
  generic Documents work, ProjectView, standalone `Term Cards`,
  `VerificationPanel`, `UserDictionariesView`, `DatabaseSwitchDialog`,
  `ProviderSettingsDialog`, `ResourcesManagerDialog`, or `ImportWizard`
  without new evidence gates.

## Nineteenth framework-driven cold-audit wave

The nineteenth official task-specific use of the canonical framework is now
recorded in:

- `docs/FIRST_RUN_WIZARD_COLD_AUDIT_2026-03-13.md`
- `docs/FIRST_RUN_WIZARD_REPAIR_2026-03-13.md`

Wave outcome:

- after the original bounded visible candidate sweep was exhausted, a new
  bounded remaining-surface sweep compared:
  - `first_run_wizard`: `4.273s`
  - `audio_provider_settings`: `0.121s`
  - `reference_setup_wizard`: `0.017s`
  - `help_center`: `0.006s`
- strict read-only approved-target-backed breakdown then confirmed the actual
  blocker shape:
  - full `FirstRunWizardDialog` cold open: `4.273s`
  - `HealthCheckService.run_all()`: `3.992s`
  - `PhonikudAdapter` pronunciation bootstrap check: `2.378s`
  - sentence niqqud bootstrap check: `1.970s`
  - DB/profile inspection: `0.005s`
  - resource status refreshes: `0.001s` to `0.003s`

Current status after the wave:

- first-run wizard cold-audit evidence gate was crossed and the bounded repair
  was opened;
- the first-run wizard `P0` blocker is now operationally closed:
  - `FirstRunWizardDialog` init now returns in `0.034s`;
  - health summary now completes later in `5.254s`;
  - the wizard opens immediately usable on page `0 / 6`;
  - the health section now opens in:
    - `Checking health summary in background...`
  - the final background summary still resolves to:
    - `Health summary ready (warn).`
- the repaired contract keeps the right scope boundaries:
  - DB/profile inspection remains immediate;
  - resource status remains immediate;
  - `HealthCheckService` semantics remain unchanged;
  - the heavy health probes remain stage-2 completeness work only;
- approved-target after evidence still records `db_mtime_unchanged=true`;
- no immediate residual first-run branch is opened from this repair;
- the next active work returns to the canonical cold-audit framework for the
  next narrow subsystem wave;
- do not reopen startup, picker, Sentences filtered-tail, Dictionary, Terms,
  Concordance, TM residual-tail, Coverage residual-tail, Audio Add-All,
  generic Documents work, ProjectView, standalone `Term Cards`,
  `VerificationPanel`, `UserDictionariesView`, `DatabaseSwitchDialog`,
  `ProviderSettingsDialog`, `ResourcesManagerDialog`, `ImportWizard`,
  `ReferenceSetupWizard`, `HelpCenterDialog`, or generic first-run work
  without new evidence gates.

## Twentieth framework-driven cold-audit wave

The twentieth official task-specific use of the canonical framework is now
recorded in:

- `docs/AUDIO_PROVIDER_SETTINGS_DIALOG_COLD_AUDIT_2026-03-13.md`

Wave outcome:

- after first-run repair returned the branch to the framework, the next
  remaining visible candidate from the bounded sweep was:
  - `audio_provider_settings`: `0.121s`
- dedicated current-state evidence then confirmed the actual contract:
  - full `AudioProviderSettingsDialog` init: `0.138s`
  - `_load_settings()`: `0.106s`
  - `_load_google_advanced_settings()`: `0.104s`
  - `_refresh_usage("google_cloud_tts")`: `0.001s`
- current dialog state stayed bounded:
  - tabs: `4`
  - chain rows: `5`
  - master enabled: `true`
  - current advanced provider: `google_cloud_tts`
- the only drift surfaced during open was separate dependency health:
  - current-machine warning:
    - `Failed to read credential audio_provider:google_cloud_tts:service_account_json: Failed to decrypt credential: Decryption failed: authentication tag invalid (data corrupted or tampered)`

Current status after the wave:

- `AudioProviderSettingsDialog` is now formally classified from current evidence;
- current classification is:
  - `blocker = no`
  - `priority = P3`
- no immediate `AudioProviderSettingsDialog` repair branch is opened from this wave;
- the decrypt warning is tracked as a separate audio credential-health gate,
  not as a cold-latency branch;
- the next active work returns to the canonical cold-audit framework for the
  next narrow subsystem wave;
- do not reopen startup, picker, Sentences filtered-tail, Dictionary, Terms,
  Concordance, TM residual-tail, Coverage residual-tail, Audio Add-All,
  generic Documents work, ProjectView, standalone `Term Cards`,
  `VerificationPanel`, `UserDictionariesView`, `DatabaseSwitchDialog`,
  MT `ProviderSettingsDialog`, `ResourcesManagerDialog`, `ImportWizard`,
  `ReferenceSetupWizard`, `HelpCenterDialog`, generic first-run work, or
  `AudioProviderSettingsDialog` without new evidence gates.

## Twenty-first framework-driven cold-audit wave

The twenty-first official task-specific use of the canonical framework is now
recorded in:

- `docs/SENTENCE_NIQQUD_BOOTSTRAP_DIALOG_COLD_AUDIT_2026-03-13.md`

Wave outcome:

- after the audio-provider-settings wave, a bounded remaining-dialog sweep
  compared:
  - `sentence_niqqud_bootstrap_dialog`: `0.039s`
  - `command_palette_dialog`: `0.021s`
  - `pronunciation_bootstrap_dialog`: `0.011s`
  - `translate_text_dialog`: `0.006s`
- the dedicated dialog-open probe then confirmed the actual constructor path:
  - full `SentenceNiqqudBootstrapDialog` init: `0.020s`
  - `_load_settings()`: `0.000s`
  - default scope on open: `selected`
  - `Run Bootstrap` enabled: `true`
  - cached health label on open:
    - `Mode: real_inference (ok)`
  - `has_worker_on_open = false`
  - `has_health_worker_on_open = false`

Current status after the wave:

- `SentenceNiqqudBootstrapDialog` is now formally classified from current evidence;
- current classification is:
  - `blocker = no`
  - `priority = P3`
- no immediate `SentenceNiqqudBootstrapDialog` repair branch is opened from this wave;
- the dialog open path is already bounded:
  - shell construction is fast;
  - cached health-state restore is negligible;
  - no health-check or bootstrap worker is started on open;
- the next active work returns to the canonical cold-audit framework for the
  next narrow subsystem wave;
- do not reopen startup, picker, Sentences filtered-tail, Dictionary, Terms,
  Concordance, TM residual-tail, Coverage lemma-count residual-tail,
  Audio Add-All, generic Documents work, ProjectView, standalone `Term Cards`,
  `VerificationPanel`, `UserDictionariesView`, `DatabaseSwitchDialog`,
  MT `ProviderSettingsDialog`, `ResourcesManagerDialog`, `ImportWizard`,
  generic first-run work, `AudioProviderSettingsDialog`, or
  `SentenceNiqqudBootstrapDialog` without new evidence gates.

## Twenty-second framework-driven cold-audit wave

The twenty-second official task-specific use of the canonical framework is now
recorded in:

- `docs/COMMAND_PALETTE_DIALOG_COLD_AUDIT_2026-03-13.md`

Wave outcome:

- after the sentence-niqqud wave, the bounded remaining-dialog sweep still
  showed:
  - `command_palette_dialog`: `0.021s`
  - `pronunciation_bootstrap_dialog`: `0.011s`
  - `translate_text_dialog`: `0.006s`
- because the sweep used an empty palette registry, a dedicated
  representative-action-set probe was required for a real conclusion;
- the dedicated probe then confirmed the actual open/search contract:
  - full `CommandPaletteDialog` init: `0.128s`
  - registry actions: `16`
  - initial results count: `16`
  - initial status:
    - `16 action(s)`
  - representative search query `audio`: `0.001s`
  - filtered results count: `2`

Current status after the wave:

- `CommandPaletteDialog` is now formally classified from current evidence;
- current classification is:
  - `blocker = no`
  - `priority = P3`
- no immediate `CommandPaletteDialog` repair branch is opened from this wave;
- the palette contract is already bounded:
  - open is fully in-memory;
  - initial population is small;
  - representative live filtering is effectively instant;
- the next active work returns to the canonical cold-audit framework for the
  next narrow subsystem wave;
- do not reopen startup, picker, Sentences filtered-tail, Dictionary, Terms,
  Concordance, TM residual-tail, Coverage lemma-count residual-tail,
  Audio Add-All, generic Documents work, ProjectView, standalone `Term Cards`,
  `VerificationPanel`, `UserDictionariesView`, `DatabaseSwitchDialog`,
  MT `ProviderSettingsDialog`, `ResourcesManagerDialog`, `ImportWizard`,
  generic first-run work, `AudioProviderSettingsDialog`,
  `SentenceNiqqudBootstrapDialog`, or `CommandPaletteDialog` without new
  evidence gates.

## Twenty-third framework-driven cold-audit wave

The twenty-third official task-specific use of the canonical framework is now
recorded in:

- `docs/PRONUNCIATION_BOOTSTRAP_DIALOG_COLD_AUDIT_2026-03-14.md`

Wave outcome:

- after the command-palette wave, the bounded remaining-dialog sweep still
  showed:
  - `pronunciation_bootstrap_dialog`: `0.011s`
  - `translate_text_dialog`: `0.006s`
- the dedicated representative-selection probe then confirmed the actual
  constructor path:
  - full `PronunciationBootstrapDialog` init: `0.115s`
  - `_load_settings()`: `0.000s`
  - representative selected items: `3`
  - selection scope:
    - `Selection scope: 3 row(s) from current table.`
  - `Run Bootstrap` enabled: `true`
  - cached health label on open:
    - `Mode: real_inference (ok)`
  - `has_health_worker_on_open = false`
  - `has_bootstrap_worker_on_open = false`

Current status after the wave:

- `PronunciationBootstrapDialog` is now formally classified from current evidence;
- current classification is:
  - `blocker = no`
  - `priority = P3`
- no immediate `PronunciationBootstrapDialog` repair branch is opened from this wave;
- the dialog open path is already bounded:
  - shell construction is fast;
  - cached health-state restore is negligible;
  - representative selection-state restore is negligible;
  - no health-check or bootstrap worker is started on open;
- the next active work returns to the canonical cold-audit framework for the
  next narrow subsystem wave;
- do not reopen startup, picker, Sentences filtered-tail, Dictionary, Terms,
  Concordance, TM residual-tail, Coverage lemma-count residual-tail,
  Audio Add-All, generic Documents work, ProjectView, standalone `Term Cards`,
  `VerificationPanel`, `UserDictionariesView`, `DatabaseSwitchDialog`,
  MT `ProviderSettingsDialog`, `ResourcesManagerDialog`, `ImportWizard`,
  generic first-run work, `AudioProviderSettingsDialog`,
  `SentenceNiqqudBootstrapDialog`, `CommandPaletteDialog`, or
  `PronunciationBootstrapDialog` without new evidence gates.

## Twenty-fourth framework-driven cold-audit wave

The twenty-fourth official task-specific use of the canonical framework is now
recorded in:

- `docs/TRANSLATE_TEXT_DIALOG_COLD_AUDIT_2026-03-14.md`

Wave outcome:

- after the pronunciation-bootstrap wave, the last remaining dialog candidate
  from the bounded sweep was:
  - `translate_text_dialog`: `0.006s`
- because the coarse sweep undercounted the real open contract, a dedicated
  follow-up probe was required;
- the dedicated probe then confirmed the actual constructor path:
  - full `TranslateTextDialog` init: `0.198s`
  - source-language count: `12`
  - target-language count: `12`
  - representative initial text length: `9`
  - selected source language: `he`
  - selected target language: `en`
  - `Translate` enabled: `true`
  - metadata label on open:
    - `No translation yet`
  - `has_worker_on_open = false`

Current status after the wave:

- `TranslateTextDialog` is now formally classified from current evidence;
- current classification is:
  - `blocker = no`
  - `priority = P3`
- no immediate `TranslateTextDialog` repair branch is opened from this wave;
- the dialog open path is already bounded:
  - eager `TranslationService()` construction is local and cheap;
  - language-combo population is small;
  - no worker/provider runtime work starts on open;
- the next active work returns to the canonical cold-audit framework for the
  next narrow subsystem wave or a new bounded candidate sweep;
- do not reopen startup, picker, Sentences filtered-tail, Dictionary, Terms,
  Concordance, TM residual-tail, Coverage lemma-count residual-tail,
  Audio Add-All, generic Documents work, ProjectView, standalone `Term Cards`,
  `VerificationPanel`, `UserDictionariesView`, `DatabaseSwitchDialog`,
  MT `ProviderSettingsDialog`, `ResourcesManagerDialog`, `ImportWizard`,
  generic first-run work, `AudioProviderSettingsDialog`,
  `SentenceNiqqudBootstrapDialog`, `CommandPaletteDialog`,
  `PronunciationBootstrapDialog`, or `TranslateTextDialog` without new
  evidence gates.

## Twenty-fifth framework-driven cold-audit wave

The twenty-fifth official task-specific use of the canonical framework is now
recorded in:

- `docs/REFERENCE_SETUP_WIZARD_COLD_AUDIT_2026-03-14.md`

Wave outcome:

- after the bounded dialog sweep was exhausted, the next largest still
  unformalized visible candidate from the prior remaining-visible sweep was:
  - `reference_setup_wizard`: `0.017s`
  - lower remaining candidate:
    - `help_center`: `0.006s`
- because the coarse sweep undercounted the real open contract, a dedicated
  follow-up probe was required;
- the dedicated probe then confirmed the actual constructor path:
  - full `ReferenceSetupWizard` init: `0.224s`
  - page count: `3`
  - current page on open: `0`
  - selected mode on open: `download`
  - `Next` enabled: `true`
  - `Back` enabled: `false`
  - `Cancel` enabled: `true`
  - `has_worker_on_open = false`

Current status after the wave:

- `ReferenceSetupWizard` is now formally classified from current evidence;
- current classification is:
  - `blocker = no`
  - `priority = P3`
- no immediate `ReferenceSetupWizard` repair branch is opened from this wave;
- the wizard open path is already bounded:
  - shell/page construction is cheap;
  - default mode state is deterministic;
  - no setup worker starts on open;
- the next active work returns to the canonical cold-audit framework for the
  next narrow subsystem wave or a new bounded candidate sweep;
- do not reopen startup, picker, Sentences filtered-tail, Dictionary, Terms,
  Concordance, TM residual-tail, Coverage lemma-count residual-tail,
  Audio Add-All, generic Documents work, ProjectView, standalone `Term Cards`,
  `VerificationPanel`, `UserDictionariesView`, `DatabaseSwitchDialog`,
  MT `ProviderSettingsDialog`, `ResourcesManagerDialog`, `ImportWizard`,
  generic first-run work, `AudioProviderSettingsDialog`,
  `SentenceNiqqudBootstrapDialog`, `CommandPaletteDialog`,
  `PronunciationBootstrapDialog`, `TranslateTextDialog`, or
  `ReferenceSetupWizard` without new evidence gates.

## Twenty-sixth framework-driven cold-audit wave

The twenty-sixth official task-specific use of the canonical framework is now
recorded in:

- `docs/HELP_CENTER_DIALOG_COLD_AUDIT_2026-03-14.md`

Wave outcome:

- after the reference-setup wave, the last remaining visible candidate from
  that bounded sweep was:
  - `help_center`: `0.006s`
- because the coarse sweep undercounted the real open contract, a dedicated
  follow-up probe was required;
- the dedicated probe then confirmed the actual constructor path:
  - full `HelpCenterDialog` init: `0.129s`
  - tab count: `5`
  - tab titles:
    - `Overview`
    - `Shortcuts`
    - `Keyboard Flows`
    - `Translation`
    - `Audio`
  - markdown views: `5`
  - window title:
    - `Help Center`

Current status after the wave:

- `HelpCenterDialog` is now formally classified from current evidence;
- current classification is:
  - `blocker = no`
  - `priority = P3`
- no immediate `HelpCenterDialog` repair branch is opened from this wave;
- the dialog open path is already bounded:
  - local markdown reads are cheap;
  - tab construction is cheap;
  - no DB, worker, or network dependency exists on open;
- the next active work returns to the canonical cold-audit framework for the
  next narrow subsystem wave or a new bounded candidate sweep;
- do not reopen startup, picker, Sentences filtered-tail, Dictionary, Terms,
  Concordance, TM residual-tail, Coverage lemma-count residual-tail,
  Audio Add-All, generic Documents work, ProjectView, standalone `Term Cards`,
  `VerificationPanel`, `UserDictionariesView`, `DatabaseSwitchDialog`,
  MT `ProviderSettingsDialog`, `ResourcesManagerDialog`, `ImportWizard`,
  generic first-run work, `AudioProviderSettingsDialog`,
  `SentenceNiqqudBootstrapDialog`, `CommandPaletteDialog`,
  `PronunciationBootstrapDialog`, `TranslateTextDialog`,
  `ReferenceSetupWizard`, or `HelpCenterDialog` without new evidence gates.

## Twenty-seventh framework-driven cold-audit wave

The twenty-seventh official task-specific use of the canonical framework is now
recorded in:

- `docs/SYSTEM_HEALTH_CHECK_ACTION_COLD_AUDIT_2026-03-14.md`

Wave outcome:

- after visible/dialog sweeps were closed, a new bounded top-level action sweep
  compared:
  - `system_health_check_action`: `0.000408s`
  - `about_dialog_action`: `0.000003s`
- the dedicated trigger-path probe then confirmed the actual contract:
  - system health check trigger path: `0.000408s`
  - immediate status message:
    - `Running health check...`
  - worker created: `true`
  - worker started: `true`
  - worker cleared immediately: `false`

Current status after the wave:

- `System Health Check` trigger path is now formally classified from current evidence;
- current classification is:
  - `blocker = no`
  - `priority = P3`
- no immediate `System Health Check` trigger-path repair branch is opened from this wave;
- the action contract is already bounded:
  - trigger path is effectively instant;
  - heavy health work stays background-only;
  - immediate operator feedback is present;
- the next active work returns to the canonical cold-audit framework for the
  next narrow subsystem wave or a new bounded candidate sweep;
- do not reopen startup, picker, Sentences filtered-tail, Dictionary, Terms,
  Concordance, TM residual-tail, Coverage lemma-count residual-tail,
  Audio Add-All, generic Documents work, ProjectView, standalone `Term Cards`,
  `VerificationPanel`, `UserDictionariesView`, `DatabaseSwitchDialog`,
  MT `ProviderSettingsDialog`, `ResourcesManagerDialog`, `ImportWizard`,
  generic first-run work, `AudioProviderSettingsDialog`,
  `SentenceNiqqudBootstrapDialog`, `CommandPaletteDialog`,
  `PronunciationBootstrapDialog`, `TranslateTextDialog`,
  `ReferenceSetupWizard`, `HelpCenterDialog`, or `System Health Check`
  trigger-path work without new evidence gates.

## Twenty-eighth framework-driven cold-audit wave

The twenty-eighth official task-specific use of the canonical framework is now
recorded in:

- `docs/ABOUT_DIALOG_ACTION_COLD_AUDIT_2026-03-14.md`

Wave outcome:

- after the top-level action sweep recorded:
  - `system_health_check_action`: `0.000408s`
  - `about_dialog_action`: `0.000003s`
- the dedicated about-action probe then confirmed the actual trigger contract:
  - about trigger path: `0.000005s`
  - detail lines: `6`
  - title:
    - `About HDLE Premium`
  - runtime payload fields:
    - `version = 1.0.0`
    - `commit = unknown`
    - `dirty = 0`
    - `built_at_utc = unknown`

Current status after the wave:

- `About HDLE Premium` trigger path is now formally classified from current evidence;
- current classification is:
  - `blocker = no`
  - `priority = P3`
- no immediate `About HDLE Premium` trigger-path repair branch is opened from this wave;
- the action contract is already bounded:
  - trigger path is effectively instant;
  - runtime build-meta formatting is tiny;
  - no DB, worker, or network dependency exists on the action path;
- the next active work returns to the canonical cold-audit framework for the
  next narrow subsystem wave or a new bounded candidate sweep;
- do not reopen startup, picker, Sentences filtered-tail, Dictionary, Terms,
  Concordance, TM residual-tail, Coverage lemma-count residual-tail,
  Audio Add-All, generic Documents work, ProjectView, standalone `Term Cards`,
  `VerificationPanel`, `UserDictionariesView`, `DatabaseSwitchDialog`,
  MT `ProviderSettingsDialog`, `ResourcesManagerDialog`, `ImportWizard`,
  generic first-run work, `AudioProviderSettingsDialog`,
  `SentenceNiqqudBootstrapDialog`, `CommandPaletteDialog`,
  `PronunciationBootstrapDialog`, `TranslateTextDialog`,
  `ReferenceSetupWizard`, `HelpCenterDialog`, `System Health Check`
  trigger-path work, or `About HDLE Premium` trigger-path work without new
  evidence gates.

## Twenty-ninth framework-driven cold-audit wave

The twenty-ninth official task-specific use of the canonical framework is now
recorded in:

- `docs/BATCH_TRANSLATE_DIALOG_COLD_AUDIT_2026-03-14.md`

Wave outcome:

- after the top-level action wave closed `About HDLE Premium`, one remaining
  unformalized user-visible cold candidate was:
  - `BatchTranslateDialog`
- the dedicated representative probe then confirmed the actual open contract:
  - full `BatchTranslateDialog` init: `0.206s`
  - representative selected rows: `25`
  - representative filtered count: `387,639`
  - restored provider mode:
    - `force:google_cloud_translate`
  - restored write mode:
    - `OVERWRITE`
  - `Translate` enabled: `true`
  - `has_worker_on_open = false`

Current status after the wave:

- `BatchTranslateDialog` cold-open path is now formally classified from current evidence;
- current classification is:
  - `blocker = no`
  - `priority = P3`
- no immediate `BatchTranslateDialog` repair branch is opened from this wave;
- the dialog open contract is already bounded:
  - local widget construction is cheap;
  - persisted `QSettings` restore is cheap;
  - no DB, worker, or network dependency exists on open;
- the next active work returns to the canonical cold-audit framework for the
  next narrow subsystem wave or a new bounded candidate sweep;
- do not reopen startup, picker, Sentences filtered-tail, Dictionary, Terms,
  Concordance, TM residual-tail, Coverage lemma-count residual-tail,
  Audio Add-All, generic Documents work, ProjectView, standalone `Term Cards`,
  `VerificationPanel`, `UserDictionariesView`, `DatabaseSwitchDialog`,
  MT `ProviderSettingsDialog`, `ResourcesManagerDialog`, `ImportWizard`,
  generic first-run work, `AudioProviderSettingsDialog`,
  `SentenceNiqqudBootstrapDialog`, `CommandPaletteDialog`,
  `PronunciationBootstrapDialog`, `TranslateTextDialog`,
  `ReferenceSetupWizard`, `HelpCenterDialog`, `System Health Check`
  trigger-path work, `About HDLE Premium` trigger-path work, or
  `BatchTranslateDialog` cold-open work without new evidence gates.

## Thirtieth framework-driven cold-audit wave

The thirtieth official task-specific use of the canonical framework is now
recorded in:

- `docs/BATCH_AUDIO_DIALOG_COLD_AUDIT_2026-03-14.md`

Wave outcome:

- after the batch-translate dialog wave closed, one remaining unformalized
  user-visible cold candidate was:
  - `BatchAudioDialog`
- the dedicated representative probe then confirmed the actual open contract:
  - full `BatchAudioDialog` init: `0.187s`
  - representative selected rows: `25`
  - representative filtered count: `387,639`
  - restored provider mode:
    - `force:google_cloud_tts`
  - restored write mode:
    - `REGENERATE_ALL`
  - provider count:
    - `5`
  - `has_worker_on_open = false`

Current status after the wave:

- `BatchAudioDialog` cold-open path is now formally classified from current evidence;
- current classification is:
  - `blocker = no`
  - `priority = P3`
- no immediate `BatchAudioDialog` repair branch is opened from this wave;
- the dialog open contract is already bounded:
  - local widget construction is cheap;
  - provider-registry listing is cheap;
  - no DB, worker, or network dependency exists on open;
- the next active work returns to the canonical cold-audit framework for the
  next narrow subsystem wave or a new bounded candidate sweep;
- do not reopen startup, picker, Sentences filtered-tail, Dictionary, Terms,
  Concordance, TM residual-tail, Coverage lemma-count residual-tail,
  Audio Add-All, generic Documents work, ProjectView, standalone `Term Cards`,
  `VerificationPanel`, `UserDictionariesView`, `DatabaseSwitchDialog`,
  MT `ProviderSettingsDialog`, `ResourcesManagerDialog`, `ImportWizard`,
  generic first-run work, `AudioProviderSettingsDialog`,
  `SentenceNiqqudBootstrapDialog`, `CommandPaletteDialog`,
  `PronunciationBootstrapDialog`, `TranslateTextDialog`,
  `ReferenceSetupWizard`, `HelpCenterDialog`, `System Health Check`
  trigger-path work, `About HDLE Premium` trigger-path work,
  `BatchTranslateDialog` cold-open work, or `BatchAudioDialog` cold-open work
  without new evidence gates.

## Thirty-first framework-driven cold-audit wave

The thirty-first official task-specific use of the canonical framework is now
recorded in:

- `docs/ADD_TO_USER_DICTIONARY_DIALOG_COLD_AUDIT_2026-03-14.md`

Wave outcome:

- after the batch-audio dialog wave closed, one remaining unformalized
  user-visible cold candidate was:
  - `AddToUserDictionaryDialog`
- the dedicated approved-target read-only probe then confirmed the actual open
  contract:
  - full `AddToUserDictionaryDialog` init: `0.180s`
  - `list_dictionaries()`: `0.069s`
  - representative selected rows: `25`
  - dictionary count:
    - `1`
  - combo count:
    - `1`
  - `has_worker_on_open = false`
  - `db_mtime_unchanged = true`

Current status after the wave:

- `AddToUserDictionaryDialog` cold-open path is now formally classified from current evidence;
- current classification is:
  - `blocker = no`
  - `priority = P3`
- no immediate `AddToUserDictionaryDialog` repair branch is opened from this wave;
- the dialog open contract is already bounded:
  - one DB-backed dictionary-list read exists on open;
  - that read is still cheap on the approved target;
  - no worker, write path, or network dependency exists on open;
- the next active work returns to the canonical cold-audit framework for the
  next narrow subsystem wave or a new bounded candidate sweep;
- do not reopen startup, picker, Sentences filtered-tail, Dictionary, Terms,
  Concordance, TM residual-tail, Coverage lemma-count residual-tail,
  Audio Add-All, generic Documents work, ProjectView, standalone `Term Cards`,
  `VerificationPanel`, `UserDictionariesView`, `DatabaseSwitchDialog`,
  MT `ProviderSettingsDialog`, `ResourcesManagerDialog`, `ImportWizard`,
  generic first-run work, `AudioProviderSettingsDialog`,
  `SentenceNiqqudBootstrapDialog`, `CommandPaletteDialog`,
  `PronunciationBootstrapDialog`, `TranslateTextDialog`,
  `ReferenceSetupWizard`, `HelpCenterDialog`, `System Health Check`
  trigger-path work, `About HDLE Premium` trigger-path work,
  `BatchTranslateDialog` cold-open work, `BatchAudioDialog` cold-open work, or
  `AddToUserDictionaryDialog` cold-open work without new evidence gates.

## Thirty-second framework-driven cold-audit wave

The thirty-second official task-specific use of the canonical framework is now
recorded in:

- `docs/EDIT_PRONUNCIATION_DIALOG_COLD_AUDIT_2026-03-14.md`

Wave outcome:

- after the add-to-user-dictionary dialog wave closed, one remaining
  unformalized user-visible cold candidate was:
  - `EditPronunciationDialog`
- the dedicated approved-target read-only reject-path probe then confirmed the
  actual trigger/open contract:
  - full reject-path trigger: `0.170s`
  - `get_entry()`: `0.070s`
  - dialog init: `0.169s`
  - existing entry found:
    - `false`
  - `changed = false`
  - `db_mtime_unchanged = true`

Current status after the wave:

- `EditPronunciationDialog` cold-open path is now formally classified from current evidence;
- current classification is:
  - `blocker = no`
  - `priority = P3`
- no immediate `EditPronunciationDialog` repair branch is opened from this wave;
- the dialog trigger/open contract is already bounded:
  - one DB-backed pronunciation lookup exists before open;
  - that lookup is still cheap on the approved target;
  - no worker, write path, or network dependency exists on open;
- the next active work returns to the canonical cold-audit framework for the
  next narrow subsystem wave or a new bounded candidate sweep;
- do not reopen startup, picker, Sentences filtered-tail, Dictionary, Terms,
  Concordance, TM residual-tail, Coverage lemma-count residual-tail,
  Audio Add-All, generic Documents work, ProjectView, standalone `Term Cards`,
  `VerificationPanel`, `UserDictionariesView`, `DatabaseSwitchDialog`,
  MT `ProviderSettingsDialog`, `ResourcesManagerDialog`, `ImportWizard`,
  generic first-run work, `AudioProviderSettingsDialog`,
  `SentenceNiqqudBootstrapDialog`, `CommandPaletteDialog`,
  `PronunciationBootstrapDialog`, `TranslateTextDialog`,
  `ReferenceSetupWizard`, `HelpCenterDialog`, `System Health Check`
  trigger-path work, `About HDLE Premium` trigger-path work,
  `BatchTranslateDialog` cold-open work, `BatchAudioDialog` cold-open work,
  `AddToUserDictionaryDialog` cold-open work, or `EditPronunciationDialog`
  cold-open work without new evidence gates.

## Decision note

The roadmap above is intentionally about **controllability and optimization**,
not about reopening the bounded snapshot-backfill track. That track remains in
hold-state until a separate decision gate is triggered.

## Residual decision note: Dictionary lemma_fts parity-health

The narrow post-hunt residual decision for Dictionary search is now recorded in:

- `docs/DICTIONARY_LEMMA_FTS_DECISION_2026-03-14.md`

Current status from canonical evidence and current code inspection:

- Dictionary default cold-open work remains closed:
  - default first page ~= `0.003s`
  - default exact count (cold) ~= `0.129s`
- the remaining Dictionary issue is not cold-open latency:
  - it is approved-target `lemma_fts` parity-health drift
  - `lemma` rows = `2,071,947`
  - `lemma_fts` rows = `2,076,909`
  - extra `lemma_fts` rows = `4,962`
- current repo behavior still depends on rowid parity:
  - Dictionary search uses
    `lemma_id IN (SELECT rowid FROM lemma_fts MATCH ...)`
- current repo repair surface is not sufficient for this branch:
  - `ensure_lemma_fts_health()` creates/populates when missing but does not
    repair already-populated parity drift
  - `scripts/repair_fts_schema.py` covers `sentence_fts` and `term_fts`, not
    `lemma_fts`

Current classification:

- `status = decision-gated`
- `priority = P1`
- `open runtime patch now = no`

Engineering meaning:

- this remains a real candidate only as a **bounded Dictionary
  correctness/FTS-health branch**
- it is not an automatic continuation of the cold-open program
- do not reopen generic Dictionary cold work or generic `P3` sweeps from this
  note

## Bounded Dictionary lemma_fts repair branch

The bounded repair follow-up for the Dictionary parity issue is now recorded in:

- `docs/DICTIONARY_LEMMA_FTS_REPAIR_2026-03-14.md`

Repair outcome:

- Dictionary open remains objectively not a cold blocker:
  - default first page ~= `0.003s`
  - default exact count (cold) ~= `0.129s`
- the repo now contains a canonical repair path for `lemma_fts` parity drift:
  - `inspect_lemma_fts_parity()` in `app/infra/fts_manager.py`
  - `rebuild_lemma_fts()` in `app/infra/fts_manager.py`
  - `scripts/repair_lemma_fts.py`
- the repair path is bounded and explicit:
  - no silent startup parity rebuild was added
  - no generic fallback/semantics rewrite was opened
- regression-locked synthetic before/after evidence now proves the intended
  branch effect:
  - before repair:
    - service search = `0`
    - `LIKE` = `1`
    - raw `lemma_fts MATCH` = `1`
  - after repair:
    - service search = `1`
    - parity probe becomes healthy

Current status after the branch:

- Dictionary cold-open work remains closed;
- Dictionary `lemma_fts` parity-health is no longer just an undocumented
  residual issue;
- a canonical bounded repair path now exists;
- applying that repair to a concrete unhealthy DB is an explicit operator step,
  not a new wide cold-audit program.

## Dictionary search correctness rollout

The first product-facing rollout follow-up for the Dictionary parity branch is
now recorded in:

- `docs/DICTIONARY_SEARCH_CORRECTNESS_ROLLOUT_2026-03-15.md`

Current status after the rollout:

- Dictionary open remains objectively not a cold blocker:
  - default first page ~= `0.003s`
  - default exact count (cold) ~= `0.129s`
- runtime Dictionary search no longer blindly trusts `lemma_fts` existence:
  - healthy `lemma_fts` keeps the FTS path;
  - unhealthy `lemma_fts` parity now falls back to `LIKE`;
  - the fallback warns once and points to
    `python scripts/repair_lemma_fts.py --db-path "<db-path>"`
- parity inspection is now cached per DB path for bounded runtime cost

Engineering meaning:

- this closes the most immediate user-facing search trust risk without
  reopening generic cold work;
- the canonical offline `lemma_fts` repair path remains the real restore path;
- any future Dictionary work should now be treated as search-semantics or
  product UX work, not as a leftover cold-open branch.

## Coverage / QA reporting phase 1

The next bounded product-facing wave after Dictionary rollout is now recorded
in:

- `docs/COVERAGE_REPORTING_PHASE1_2026-03-15.md`

Current status after the wave:

- the existing `QA / Coverage` panel keeps its staged first-usable-state
  contract intact;
- operators can now copy the current panel state into the clipboard;
- operators can now export a lightweight text/markdown coverage report from the
  current panel state;
- report generation reuses already-loaded panel data and does not introduce a
  new worker/query pipeline.

Engineering meaning:

- this turns Coverage from a pure inspection panel into a bounded handoff
  surface;
- it avoids reopening coverage computation or export-center redesign;
- any future coverage work should now focus on stronger report formats or
  broader product workflow integration, not on another rescue branch.

## Guided onboarding / reconnect UX phase 1

The next bounded product-facing wave after Coverage reporting is now recorded
in:

- `docs/GUIDED_ONBOARDING_RECONNECT_PHASE1_2026-03-15.md`

Current status after the wave:

- the first-run wizard keeps its staged/background health-summary contract;
- the health page now surfaces severity counts for the current report;
- the health page now shows a recommended next step;
- the health page now enables context fix buttons only for actionable
  `warn` / `error` categories in the current report.

Engineering meaning:

- this improves operator guidance without changing health-check semantics;
- it does not reopen cold, reconnect, or provider/resource redesign work;
- any future onboarding work should now focus on broader flow coherence rather
  than raw health-summary visibility.

## Residual decision note: Concordance sentence_fts dependency-health

The narrow residual decision for the Concordance dependency gate is now
recorded in:

- `docs/CONCORDANCE_SENTENCE_FTS_DECISION_2026-03-14.md`

Current status from canonical evidence and current repo inspection:

- Concordance remains blocked by prerequisite `sentence_fts` health on the
  approved target:
  - `sentence_fts` rows = `1,792`
  - project `1` sentence rows = `13,387,588`
  - project-joined `sentence_fts` rows = `0`
- this remains a real `P1` dependency-health topic if Concordance still
  matters;
- unlike the Dictionary `lemma_fts` branch, the repo already contains a
  canonical repair path:
  - `scripts/repair_fts_schema.py`
  - `docs/FTS_SCHEMA_REPAIR.md`
  - `tests/test_repair_fts_schema.py`

Current classification:

- `status = decision-gated`
- `priority = P1`
- `open new runtime patch now = no`

Engineering meaning:

- no new repair-tool branch is justified from this point;
- the next valid step, if this branch is ever prioritized, is explicit
  application/revalidation of the existing `sentence_fts` repair path against
  the unhealthy target DB;
- Concordance latency/UI work should stay closed until that dependency-health
  gate is crossed.

## Residual decision note: Sentences filtered search/count tail

The narrow residual decision for the Sentences filtered tail is now recorded in:

- `docs/SENTENCES_FILTERED_TAIL_DECISION_2026-03-14.md`

Current status from canonical evidence and current repo inspection:

- the remaining filtered tail is still real on the approved target:
  - filtered first page ~= `1.782s` to `2.262s`
  - filtered exact count ~= `7.945s` to `8.604s`
- but the branch remains a residual workflow tail, not a default-path blocker;
- the blocked structural acceleration layer is still `sentence_fts`, and the
  approved target remains unhealthy there:
  - `document_sentence` rows = `13,389,383`
  - `sentence_fts` rows = `1,792`
  - `sentence_fts MATCH 'wiki'` = `0`
- unlike a missing-tooling branch, the repo already contains the relevant repair
  surface:
  - `scripts/repair_fts_schema.py`
  - `docs/FTS_SCHEMA_REPAIR.md`
  - `tests/test_repair_fts_schema.py`

Current classification:

- `status = decision-gated`
- `priority = P1`
- `open new runtime patch now = no`

Engineering meaning:

- no second Sentences runtime patch should open from current evidence;
- if this branch is ever prioritized, the next valid step is explicit
  application/revalidation of the existing `sentence_fts` repair path on the
  unhealthy target DB;
- only after that should the repo decide whether any residual Sentences code
  work is still justified.

## Lower-layer sentence_fts recovery completed on approved target

The approved-target lower-layer recovery is now recorded in:

- `docs/SENTENCE_FTS_LOWER_LAYER_REVALIDATION_2026-03-14.md`

Operational outcome:

- the canonical `sentence_fts` repair path was hardened first so dry-run would
  detect row-count drift, not only malformed-schema defects;
- the approved target DB then completed a real backed-up repair:
  - before: `sentence_fts = 1,792`, `document_sentence = 13,389,383`
  - after: `sentence_fts = 13,389,383`, `document_sentence = 13,389,383`
- post-repair revalidation now shows:
  - `sentence_fts MATCH 'wiki' = 140`
  - project `1` joined FTS rows = `13,387,588`
  - project `1` sentence rows = `13,387,588`

Engineering meaning:

- the old approved-target `sentence_fts` health gate is now actually crossed;
- Concordance is no longer blocked by zero project-joined FTS coverage on the
  repaired large DB;
- Sentences filtered-tail follow-up is no longer blocked by the previously
  unhealthy substrate;
- the next active stage, if work continues, is post-repair revalidation:
  - Concordance first
  - Sentences filtered search/count second

## Heavy baseline / reconnect target lower-layer recovery

The heavy baseline / reconnect target revalidation is now recorded in:

- `docs/HEWIKI_BASELINE_RECONNECT_REVALIDATION_2026-03-14.md`

Target:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db`

Operational outcome:

- before repair:
  - `schema_version = 41`
  - `sentence_fts = 0`
  - `document_sentence = 13,387,588`
  - project `1` joined FTS rows = `0`
- canonical dry-run correctly classified the defect after the repair-tool
  hardening:
  - `sentence_fts_row_mismatch: sentence_fts=0, document_sentence=13387588`
- real repair completed with backup:
  - `hewiki_gpu_processing.fts_repair_20260314_165952.db.bak`
- after repair:
  - `sentence_fts = 13,387,588`
  - `document_sentence = 13,387,588`
  - `sentence_fts MATCH 'wiki' = 140`
  - project `1` joined FTS rows = `13,387,313`
- runtime self-check:
  - `db_open = ok`
  - `health` still reports non-DB issues (bootstrap/provider/resource layer),
    not lower-layer FTS failure

Engineering meaning:

- the heavy reconnect target is now healthy at the DB/FTS layer;
- any remaining reconnect/health issues are no longer explained by the old
  `sentence_fts` defect;
- the next meaningful application-layer revalidation remains:
  - Concordance on healthy FTS
  - Sentences filtered search/count on healthy FTS

## Concordance revalidation on healthy sentence_fts

The post-repair Concordance revalidation is now recorded in:

- `docs/CONCORDANCE_REVALIDATION_2026-03-14.md`

Outcome on the repaired heavy baseline DB:

- raw project-scoped Concordance page runs:
  - `0.033s`, `0.021s`, `0.021s`
- raw project-scoped Concordance count runs:
  - `0.011s`, `0.010s`, `0.011s`
- `page_row_count = 100`
- `count_total = 665`

Current classification after revalidation:

- `status = closed`
- `priority = P3`
- `open runtime patch now = no`

Engineering meaning:

- the old Concordance dependency-health gate is now crossed on healthy
  `sentence_fts`;
- the revalidated Concordance query path is already bounded and fast;
- no further Concordance runtime/cold branch is justified from current evidence;
- the next meaningful revalidation remains Sentences filtered search/count on
  the same healthy substrate.

## Sentences filtered search/count revalidation on healthy substrate

The post-repair Sentences filtered-tail revalidation is now recorded in:

- `docs/SENTENCES_FILTERED_REVALIDATION_2026-03-14.md`

Outcome on the repaired heavy baseline DB:

- raw ordered filtered page runs:
  - `4.372s`, `1.484s`, `1.459s`
- raw unordered filtered page runs:
  - `1.470s`, `1.467s`, `1.474s`
- raw exact filtered count runs:
  - `16.531s`, `6.702s`, `6.688s`
- service filtered page runs:
  - `2.090s`, `1.892s`, `1.958s`
- service filtered count runs:
  - `7.769s`, `7.606s`, `7.656s`
- `row_count = 100`
- `total = 585`

Current classification after revalidation:

- `status = decision-gated`
- `priority = P1`
- `open second Sentences runtime patch now = no`

Engineering meaning:

- healthy `sentence_fts` removed the old dependency-health uncertainty;
- the Sentences filtered branch is now honestly measured on a healthy substrate;
- the residual tail remains real, but it still belongs to current `LIKE`
  search semantics and exact-count expectations rather than to a newly revealed
  bounded runtime defect;
- no immediate second Sentences runtime patch is justified from current
  evidence;
- the meaningful application-layer cold revalidation stage is now complete;
- the next operational step, if work continues, is the separate lower-layer
  recovery cycle for the unhealthy `hewiki_gpu_processing test.db`.

## Hewiki test DB lower-layer recovery

The separate recovery cycle for the approved-target hewiki test DB is now
recorded in:

- `docs/HEWIKI_TEST_DB_RECOVERY_2026-03-14.md`

Target:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`

Operational outcome:

- before repair, canonical dry-run reported:
  - `probe_error:count_sentence_fts: database disk image is malformed`
- real repair completed with backup:
  - `hewiki_gpu_processing test.fts_repair_20260314_181314.db.bak`
- after repair:
  - `schema_version = 65`
  - `sentence_fts = 13,389,383`
  - `document_sentence = 13,389,383`
  - `sentence_fts MATCH 'wiki' = 140`
  - project `1` joined FTS rows = `13,387,588`
- runtime self-check:
  - `db_open = ok`
  - `health = warn`
  - remaining health warnings are now higher-layer optional/provider issues, not
    lower-layer FTS failure

Engineering meaning:

- the approved-target hewiki test DB is now again healthy at the lower FTS
  layer;
- both large hewiki DB artifacts used during the cold program now have healthy
  `sentence_fts` substrates;
- the lower-layer recovery stage is complete;
- any further work should now be chosen from product-facing priorities rather
  than from unresolved cold/lower-layer blockers.

## Product-facing priority selection

The post-cold, post-recovery product-facing shortlist is now recorded in:

- `docs/PRODUCT_PRIORITY_SELECTION_2026-03-14.md`

Current decision:

- the next implementation wave is `Import and project-exchange UX completion`
- do not reopen generic cold-hunt or broad `P3` sweeps
- do not reopen lower-layer FTS recovery by default

Bounded Phase 1 target:

- add a real read-only import preflight against the current host DB
- improve `.hdleproj` preview clarity before import starts
- surface a visible import completion summary
- make `Go to Project` navigate to the imported project after success
- fail fast on corrupt source DBs during export and point operators to the
  canonical DB recovery tool instead of failing late after payload work

Implementation note for the selected wave:

- `docs/IMPORT_PROJECT_EXCHANGE_UX_PHASE1_2026-03-14.md`

Manual validation note from the same wave:

- later manual export testing on `hewiki_gpu_processing test.db` surfaced a
  repeat malformed `sentence_fts` condition;
- canonical `repair_fts_schema.py` restored the DB again;
- export now fails fast on corrupt source DBs with an explicit
  `repair_db_corruption.py` remediation hint instead of failing late after
  payload assembly.

## Release-facing ship gate phase 1

The next bounded product-facing wave after Import / Project Exchange UX Phase 1
is now recorded in:

- `docs/RELEASE_SHIP_GATE_PHASE1_2026-03-15.md`

Current implementation scope:

- strengthen `scripts/prebuild_validate.py` as an actual ship gate
- detect corrupt candidate DBs before write-heavy validation phases
- stop early with explicit `repair_db_corruption.py` remediation
- sync prebuild/release docs to the new fail-fast contract

Immediate outcome from the first live ship-gate run:

- both large hewiki DB artifacts currently fail the new corruption probe
- this means release readiness is now honestly blocked at the DB artifact level,
  not by unresolved cold branches
