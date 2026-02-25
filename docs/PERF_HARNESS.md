# Perf Harness Usage

`scripts/perf_harness.py` measures key read-path performance with repeatable
warm-up/runs and writes JSON output (`p50`/`p95`).

The harness uses direct SQLAlchemy sessions (read-path only) and does not run
migrations/prebuild write probes, so it is safe to run against readonly
reference databases.

## What it measures

- Dictionary first page (`100` rows, default filters)
- Dictionary count (same filters)
- Document Picker first page (empty search)
- Document Picker search page

## Commands (Windows / PowerShell)

```powershell
cd J:\Project_Vibe\V_book
python scripts/perf_harness.py --db-path "M:\V_book\HDLE_Processing\hewiki_gpu_processing.db" --runs 5 --warmup 1 --out perf_hewiki.json
python scripts/perf_harness.py --db-path "J:\Project_Vibe\V_book\hdle_premium.db" --runs 5 --warmup 1 --out perf_dev.json
```

## Optional arguments

- `--project-id N` force a specific project ID
- `--search-term TEXT` picker text query (default: `wiki`)
- `--runs N` measured runs (default: `5`)
- `--warmup N` warm-up runs (default: `1`)

## Output

JSON includes:

- selected project id,
- per-operation run timings,
- `p50`/`p95`,
- row counts,
- timestamp + environment metadata.

Compare results against `docs/PERFORMANCE_SLO.md`.
