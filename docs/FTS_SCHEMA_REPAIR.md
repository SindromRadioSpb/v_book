# FTS Schema Repair (Hewiki / Reference DB)

## Symptom

On startup, diagnostics, or benchmark probe:

`malformed database schema (sentence_fts) - table sentence_fts already exists`

Typical impact:

- app startup FTS self-check fails for the target DB,
- benchmark scripts cannot safely use the target DB directly,
- verification may drift to fallback/sandbox DB instead of the intended runtime DB.

## When to Run

Run once for a target DB that shows the malformed `sentence_fts` schema error.

Recommended for large reference DBs before release smoke:

- `M:\Soft\1. Data folder HDLE Local (model, dataset, logs temporary)\HDLE_Processing\hewiki_gpu_processing.db`

## Command

```powershell
python scripts/repair_fts_schema.py --db-path "M:\Soft\1. Data folder HDLE Local (model, dataset, logs temporary)\HDLE_Processing\hewiki_gpu_processing.db"
```

Useful flags:

- `--dry-run` (inspect only, no changes)
- `--no-backup` (skip backup in automated pipelines)
- `--verbose` (detailed logs)
- `--skip-rebuild` (recreate FTS schema objects without bulk repopulation)

## What the Repair Does

1. Inspects FTS health (`sentence_fts`, `term_fts`, triggers, probe queries).
2. Detects duplicate `sqlite_master` entries in FTS namespace.
3. Optionally creates DB backup (default enabled).
4. Removes duplicate master rows deterministically (keeps lowest `rowid`).
5. Drops/recreates FTS tables + triggers using canonical DDL.
6. Rebuilds FTS data from source tables.
7. Validates:
   - schema parse probe,
   - trigger presence,
   - row-count parity (`sentence_fts` vs `document_sentence`, `term_fts` vs `term_search`),
   - simple `MATCH` query for both FTS tables.

If bulk rebuild fails (for example on damaged source pages), rerun with `--skip-rebuild`
to restore schema/triggers first and unblock strict no-fallback verification.

Output:

- JSON summary printed to stdout,
- persisted report in `build/logs/fts_repair_*.json`.

## Safety Notes

- Idempotent: second run should report `status=OK` with no actions.
- Backup is enabled by default for interactive use.
- For CI/automation, use `--no-backup` only when backup lifecycle is handled externally.
- If repair returns `FAILED`, do not continue with release benchmark on that DB until resolved.
- If repair returns `REPAIRED` with rebuild warnings, run integrity diagnostics before relying on FTS content completeness.
