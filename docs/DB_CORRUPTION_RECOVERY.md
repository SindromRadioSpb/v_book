# DB Corruption Recovery (Hewiki / Reference DB)

## Symptom

Typical runtime or benchmark failure:

`database disk image is malformed`

Most visible in this project when probing `tm_entry` (for example:
`SELECT COALESCE(MAX(tm_id), 0) + 1 FROM tm_entry`).

## Goal

Produce a usable recovered DB for strict direct-mode benchmark/release smoke
without silent fallback.

Target reference DB:

- `M:\Soft\1. Data folder HDLE Local (model, dataset, logs temporary)\HDLE_Processing\hewiki_gpu_processing.db`

## Diagnose (safe, read-only)

```powershell
python scripts/repair_db_corruption.py --db-path "M:\Soft\1. Data folder HDLE Local (model, dataset, logs temporary)\HDLE_Processing\hewiki_gpu_processing.db" --diagnose-only
```

Optional deep check (long on huge DB):

```powershell
python scripts/repair_db_corruption.py --db-path "M:\Soft\1. Data folder HDLE Local (model, dataset, logs temporary)\HDLE_Processing\hewiki_gpu_processing.db" --diagnose-only --deep
```

Diagnosis output:

- `status: OK` or `CORRUPT`
- `quick_check` result
- failing object hints (`tm_entry`, indexes, open/read probes)
- SQL examples that failed

## Salvage Pipeline (.recover)

Default (safe) flow:

```powershell
python scripts/repair_db_corruption.py --db-path "M:\Soft\1. Data folder HDLE Local (model, dataset, logs temporary)\HDLE_Processing\hewiki_gpu_processing.db"
```

What it does:

1. Runs diagnostics and confirms corruption.
2. Creates backup copy by default (`*.bak_<timestamp>.db`).
3. Runs `sqlite3 .recover` into a **new recovered DB**.
4. Runs `scripts/repair_fts_schema.py` on recovered DB (schema/triggers repair path).
5. Validates recovered DB:
   - `PRAGMA quick_check(10)`,
   - `SELECT 1 FROM tm_entry LIMIT 1`,
   - FTS tables/triggers presence.
6. Reports key table count comparison (best effort) between original and recovered.

Artifacts:

- JSON summary: `build/logs/db_corruption_repair_*.json`
- recover log: `build/logs/db_recover_*.log`

## Important Flags

- `--no-backup`:
  disable backup copy (only for controlled automation).
- `--sqlite3-bin <path>`:
  explicit sqlite3 CLI path for `.recover`.
- `--recovered-db-path <path>`:
  choose output DB path.
- `--fts-rebuild`:
  full FTS repopulation after salvage (can be long on hewiki scale).

## Benchmark Integration

Benchmark now fails fast on corruption and prints remediation command:

```powershell
python scripts/benchmark_import_concurrent_save.py --db-path "<target>"
```

To benchmark recovered DB explicitly:

```powershell
python scripts/benchmark_import_concurrent_save.py --db-path "<original>" --use-repaired-db "<recovered_db>"
```

Strict behavior:

- no silent fallback for corruption,
- direct mode required for release evidence (`target_db_used == target_db_input` or explicit `--use-repaired-db` path).

## PASS Criteria

- `repair_db_corruption.py` ends with `SALVAGED_OK` or `SALVAGED_WITH_WARNINGS`.
- Validation shows:
  - `quick_check.ok = true`,
  - `tm_entry_probe.ok = true`,
  - `fts_status.ok = true`.
- Benchmark runs without fallback on selected DB path.
