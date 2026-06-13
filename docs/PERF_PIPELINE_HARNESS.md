# Real Pipeline Perf Harness (PATCH-05)

## Purpose
- Benchmark real write-heavy pipeline stages on a deterministic slice of the large reference corpus.
- Keep benchmarking safe: sandbox-only writes, no write operations on `M:\`.

## Safety Contract
- `--db-path` must be on `J:\` (sandbox DB).
- `--source-db` must be on `J:\` (local writable corpus copy).
- `--temp-root` must be on `J:\` (repo-local working copy scratch).
- `--copy-target` is mandatory.
- Runner hard-fails if `--db-path` or `--source-db` points to `M:\`.
- For each run, script clones sandbox DB into a temporary working DB and writes there.

## Scenarios
- `extract_terms`
- `niqqud_bootstrap`
- `translate_bootstrap` (Google Cloud Translate Official v3)
- `tts_bootstrap` (Google Cloud TTS)
- `all` (runs all stages in order)

## Deterministic Slice Policy
- Source project: `--source-project-id` (default `1`).
- Stable selection: `ORDER BY doc_id ASC LIMIT --doc-limit` (default `6000`).
- Runner creates/replaces staging project `BENCH_PIPELINE` in the working DB.
- Downstream stages run against that staging project only.

## Required Inputs
- Source local writable corpus DB:
  - `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db`
- Sandbox DB path:
  - `J:\Project_Vibe\V_book\build\bench\hewiki_pipeline_sandbox.db`
- Niqqud model:
  - `M:\V_book\HDLE_Processing\models\phonikud-1.0.int8.onnx`
- Google Cloud Translate key path:
  - `/path/to/gct-key-dir`
- Google Cloud TTS key path:
  - `/path/to/gctts-key-dir`

## Canonical Commands (PowerShell)
```powershell
cd /d J:\Project_Vibe\V_book

.\.venv\Scripts\python.exe scripts\benchmarks\bench_reference_pipeline.py `
  extract_terms `
  --db-path "J:\Project_Vibe\V_book\build\bench\hewiki_pipeline_sandbox.db" `
  --copy-target `
  --source-db "J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db" `
  --source-project-id 1 `
  --doc-limit 6000 `
  --overwrite 1 `
  --temp-root "J:\Project_Vibe\V_book\build\tmp\pipeline_bench_work"
```

```powershell
cd /d J:\Project_Vibe\V_book

.\.venv\Scripts\python.exe scripts\benchmarks\bench_reference_pipeline.py `
  all `
  --db-path "J:\Project_Vibe\V_book\build\bench\hewiki_pipeline_sandbox.db" `
  --copy-target `
  --source-db "J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db" `
  --source-project-id 1 `
  --doc-limit 6000 `
  --overwrite 1 `
  --temp-root "J:\Project_Vibe\V_book\build\tmp\pipeline_bench_work" `
  --phonikud-model-path "M:\V_book\HDLE_Processing\models\phonikud-1.0.int8.onnx" `
  --gct-key-path "/path/to/gct-key-dir" `
  --gctts-key-path "/path/to/gctts-key-dir"
```

## Runtime-Bound Knobs (Deterministic, Optional)
- `--lemma-limit` (default `1000`)
- `--term-limit` (default `1000`)
- `--sentence-limit` (default `1000`)
- `--pron-chunk-size`, `--sentence-chunk-size`, `--sentence-sub-chunk-size`, `--tts-commit-chunk`

These do not change ordering semantics; they only bound work volume per run.

## Artifacts
- `build\logs\pipeline_bench_latest.log`
- `build\logs\pipeline_bench_metrics_<timestamp>.json`
- `build\logs\pipeline_bench_report_<timestamp>.md`

JSON includes:
- start/end timestamps,
- rows processed per entity type (`lemma`, `term`, `sentence`),
- overwrite mode,
- stage durations,
- error counts and first 5 samples,
- absolute artifact paths.

## Common Failure Modes
- Missing/invalid key files:
  - Runner fails fast with actionable path message.
- Cloud quota/rate-limit:
  - Stage completes with error samples in JSON/MD report.
- Missing ONNX model path:
  - `niqqud_bootstrap` fails fast; set `--phonikud-model-path`.
- DB safety violation:
  - Immediate abort if target/source path is on `M:\`.
- Stale temp data after aborted runs:
  - Runner clears `--temp-root` before each run.
  - If orphan process keeps handles, terminate old python benchmark PIDs first.
