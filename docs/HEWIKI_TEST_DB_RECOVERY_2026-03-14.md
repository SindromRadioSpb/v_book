# Hewiki Test DB Lower-Layer Recovery (2026-03-14)

## Why this document exists

This note records the separate lower-layer recovery cycle for:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`

This is not a new cold-audit wave.

Its purpose is narrow:

- confirm the defect that reappeared on the approved-target large DB;
- record the guarded repair run with backup;
- record post-repair lower-layer and runtime self-check evidence.

## Preconditions

Before touching the DB:

- the meaningful application-layer cold revalidation stage was already complete;
- canonical repair tooling was already hardened and regression-checked;
- targeted repair-tool suite was rerun:
  - `tests/test_repair_fts_schema.py`
  - `tests/test_security.py`

Result:

- `38 passed`

## Defect before repair

Canonical dry-run on the target DB reported:

- `status = FAILED`
- `issues_detected = ["probe_error:count_sentence_fts: database disk image is malformed"]`

Engineering meaning:

- the target DB was no longer merely suffering from old row-count drift;
- the lower `sentence_fts` layer had reached a state where canonical probe
  reads could no longer count FTS rows safely;
- a bounded backup + repair cycle was justified.

## Real repair result

Command path used:

- `python scripts/repair_fts_schema.py --db-path "<hewiki-test-db>"`

Outcome:

- `status = REPAIRED`
- backup created:
  - `hewiki_gpu_processing test.fts_repair_20260314_181314.db.bak`

Actions completed:

- `hard_reset_fts_namespace_sqlite_master:18`
- `recreated_fts_tables_and_triggers`
- `rebuild_sentence_fts_completed`
- `rebuild_term_fts_completed`
- `fts_optimize_completed:sentence_fts`
- `fts_optimize_completed:term_fts`

Warnings recorded:

- `drop_fts_objects_failed:database disk image is malformed`

Engineering meaning:

- the malformed FTS namespace could not be cleanly dropped first;
- the repair still completed by hard-resetting the FTS namespace and rebuilding
  from source tables;
- this is still a successful bounded lower-layer recovery, not a silent partial
  success.

Canonical repair summary:

- `build/logs/fts_repair_20260314_182629.json`

## Post-repair revalidation

Post-repair dry-run:

- `status = OK`
- `issues_detected = []`

Canonical dry-run summary:

- `build/logs/fts_repair_20260314_182645.json`

Read-only lower-layer artifact:

- `build/logs/cold_audit/lower_layer/hewiki_test_recovery_2026-03-14.json`

Observed after repair:

- `schema_version = 65`
- `sentence_fts_count = 13,389,383`
- `document_sentence_count = 13,389,383`
- `sentence_fts MATCH 'wiki' = 140`
- `project1_joined_rows = 13,387,588`
- `project1_sentence_rows = 13,387,588`
- `project1_original_match_count = 666`
- `project1_original_match_elapsed_s = 1.219`

Runtime self-checks:

- `db_open = ok`
- `health = warn`

Current `health` warning state is no longer a lower-layer FTS failure. It is
now limited to higher-layer optional/provider conditions such as:

- missing cloud audio credentials;
- optional disabled MT providers;
- optional baseline bundle absence.

## What changes strategically

What is now closed:

- lower-layer recovery on the approved-target `hewiki_gpu_processing test.db`

What this means:

- both large hewiki DB artifacts used in the cold program are now healthy at
  the lower FTS layer;
- further work should no longer treat either DB as blocked by old
  `sentence_fts` substrate defects.

What is not justified automatically:

- reopening broad cold-hunt
- reopening generic P3 sweeps
- opening new runtime patches without fresh product-facing evidence
