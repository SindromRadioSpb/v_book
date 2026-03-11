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

3. **Document picker dominant search path**
   - `app/services/document_service.py`
   - `app/ui/dialogs/document_picker_dialog.py`
   - Search remains the clearest user-facing latency hotspot on hewiki-scale DBs.

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

### PATCH-P0-03: Document picker search SLO recovery

Goal:

- remove the dominant temp-sort / high-latency path in daily navigation.

Primary files:

- `app/services/document_service.py`
- `app/ui/dialogs/document_picker_dialog.py`
- supporting migration/index files
- perf tests and query-plan assertions

Expected output:

- picker search p95 restored to budget on hewiki-scale evidence,
- no regression in deterministic paging behavior.

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

## Immediate execution order

1. `PATCH-P0-01` import controllability
2. `PATCH-P0-02` runtime DB write-governance baseline
3. `PATCH-P0-03` picker search SLO recovery
4. `PATCH-P1-01` large derived data governance
5. `PATCH-P1-02` audio cache contract completion

## Decision note

The roadmap above is intentionally about **controllability and optimization**,
not about reopening the bounded snapshot-backfill track. That track remains in
hold-state until a separate decision gate is triggered.
