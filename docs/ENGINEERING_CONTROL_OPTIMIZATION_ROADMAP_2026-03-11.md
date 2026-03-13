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

## Decision note

The roadmap above is intentionally about **controllability and optimization**,
not about reopening the bounded snapshot-backfill track. That track remains in
hold-state until a separate decision gate is triggered.
