# Perf Harness Usage

`scripts/perf_harness.py` measures key read-path performance with repeatable
warm-up/runs and writes JSON output (`p50`/`p95`).

The harness uses direct SQLAlchemy sessions (read-path only) and does not run
migrations/prebuild write probes, so it is safe to run against readonly
reference databases.

Approved Task 30 reference target:

- DB path:
  `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`
- Verified schema version at initial Task 30 audit: `35`
- Current schema version after migration `038_sentence_nlp_snapshot`: `38`

## What it measures

- Dictionary first page (`100` rows, default filters)
- Dictionary count (same filters)
- Document Picker first page (empty search)
- Document Picker search page

## Commands (Windows / PowerShell)

```powershell
cd J:\Project_Vibe\V_book
python scripts/perf_harness.py --db-path "J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db" --runs 5 --warmup 1 --out build\logs\task30\perf_harness_hewiki_test.json
python scripts/perf_harness.py --db-path "J:\Project_Vibe\V_book\hdle_premium.db" --runs 5 --warmup 1 --out perf_dev.json
```

## Optional arguments

- `--project-id N` force a specific project ID
- `--search-term TEXT` picker text query (default: `wiki`)
- `--runs N` measured runs (default: `5`)
- `--warmup N` warm-up runs (default: `1`)

## Output

JSON includes:

- schema version context from the target DB artifact set,
- selected project id,
- per-operation run timings,
- `p50`/`p95`,
- row counts,
- timestamp + environment metadata.

Compare results against `docs/PERFORMANCE_SLO.md`.

## Local pytest note

If local `pytest-qt` runs fail because `%TEMP%` or `%TMP%` is not writable,
redirect them before running UI-heavy test slices:

```powershell
New-Item -ItemType Directory -Force -Path build\tmp\pytest | Out-Null
$env:TEMP = (Resolve-Path build\tmp\pytest).Path
$env:TMP = $env:TEMP
python -m pytest tests\test_health_check_service.py -q
```
