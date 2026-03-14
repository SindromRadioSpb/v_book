# Hewiki Baseline Reconnect Revalidation (2026-03-14)

## Why this document exists

This note records the lower-layer health check and repair for the heavy baseline
/ reconnect target:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db`

This is distinct from:

- the previously repaired approved-target cold DB
  `hewiki_gpu_processing test.db`
- the lightweight clean-install startup default DB
  `%LOCALAPPDATA%\HDLE\hdle.db`

The purpose here is operational:

- confirm whether the heavy baseline/reconnect target is healthy enough to be
  connected after installation;
- repair lower-layer `sentence_fts` drift if needed;
- record post-repair runtime evidence.

## Initial state

Read-only inspection before repair showed:

- `schema_version = 41`
- `sentence_fts_count = 0`
- `document_sentence_count = 13,387,588`
- `sentence_fts MATCH 'wiki' = 0`
- project `1` joined FTS rows = `0`
- project `1` sentence rows = `13,387,588`

The hardened dry-run of the canonical repair tool then reported:

- `status = FAILED`
- `issues_detected = ["sentence_fts_row_mismatch: sentence_fts=0, document_sentence=13387588"]`

Engineering meaning:

- this heavy reconnect target was not healthy enough for Concordance or any
  `sentence_fts`-dependent workflow;
- the defect matched the documented lower-layer issue class and was therefore
  safe to repair with the canonical tool.

## Real repair

Command path used:

- `python scripts/repair_fts_schema.py --db-path "<hewiki_gpu_processing.db>"`

Outcome:

- `status = REPAIRED`
- backup created:
  - `hewiki_gpu_processing.fts_repair_20260314_165952.db.bak`
- canonical summary:
  - `build/logs/fts_repair_20260314_171047.json`

Completed actions:

- dropped existing FTS tables and triggers
- recreated FTS tables and triggers
- rebuilt `sentence_fts`
- rebuilt `term_fts`
- optimized both FTS tables

## Post-repair lower-layer evidence

Revalidation artifact:

- `build/logs/cold_audit/lower_layer/hewiki_baseline_revalidation_2026-03-14.json`

Observed after repair:

- `schema_version = 41`
- `sentence_fts_count = 13,387,588`
- `document_sentence_count = 13,387,588`
- `sentence_fts MATCH 'wiki' = 140`
- project `1` joined FTS rows = `13,387,313`
- project `1` sentence rows = `13,387,588`
- project `1` `Original` match count = `665`
- project `1` `Original` match elapsed ~= `1.956s`

Post-repair dry-run:

- `status = OK`
- `issues_detected = []`

Engineering meaning:

- the heavy reconnect target is now healthy at the lower `sentence_fts` layer;
- it no longer has the zero-row FTS failure that previously invalidated
  FTS-dependent workflows.

## Runtime self-check evidence

### db_open

Command:

- `python -m app.main --self-check db_open --db-path "<hewiki_gpu_processing.db>"`

Result:

- `ok = true`
- `elapsed_ms = 21`
- sample project/document IDs were returned

Engineering meaning:

- runtime open against the heavy reconnect target works.

### health

Command:

- `python -m app.main --self-check health --db-path "<hewiki_gpu_processing.db>"`

Result:

- outer command completed successfully and returned a report
- report `overall = error`

Current non-DB findings in that report:

- `bootstrap:pronunciation` timed out after `8000ms`
- cloud audio credentials are missing
- baseline bundle is optional/missing

Engineering meaning:

- the remaining health issues are **not** lower-layer DB / FTS failures;
- they are resource/bootstrap/provider configuration issues.

## Operational conclusion

The heavy baseline / reconnect target:

- was unhealthy before repair;
- has now passed lower-layer `sentence_fts` repair and revalidation;
- can be opened by runtime self-check;
- still needs separate resource/provider health attention if the goal is a fully
  green overall `health` report.

This closes the DB/FTS part of the heavy reconnect target problem.
