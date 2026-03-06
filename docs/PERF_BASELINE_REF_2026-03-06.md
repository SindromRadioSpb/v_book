# PERF Baseline (2026-03-06) - PATCH-01A/PATCH-01B

## Scope and Safety
- Original reference DB (read-only baseline only, no writes in this run): `M:\V_book\HDLE_Processing\hewiki_gpu_processing.db`
- Writable source for benchmark work: `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db`
- Benchmark sandbox DB (write-heavy runs): `J:\Project_Vibe\V_book\build\bench\hewiki_sandbox.db`
- All write-heavy benchmark commands below targeted only `J:\...` paths.

## Commands (copy-paste, PowerShell)
```powershell
Set-Location J:\Project_Vibe\V_book

# Recreate sandbox from writable local corpus copy
New-Item -ItemType Directory -Force build\bench | Out-Null
Copy-Item -Force `
  "J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db" `
  "J:\Project_Vibe\V_book\build\bench\hewiki_sandbox.db"

# Local writable temp to avoid AppData permission/lock issues
New-Item -ItemType Directory -Force build\tmp | Out-Null
$tmp = (Resolve-Path build\tmp).Path
$env:TEMP = $tmp
$env:TMP = $tmp

# Read-path baseline (before)
.\.venv\Scripts\python.exe scripts\perf_harness.py `
  --db-path "J:\Project_Vibe\V_book\build\bench\hewiki_sandbox.db" `
  --runs 5 --warmup 1 `
  --out "build\bench\perf_baseline_before.json"

# Write-gate contention baseline (before)
.\.venv\Scripts\python.exe scripts\benchmark_import_concurrent_save.py `
  --db-path "J:\Project_Vibe\V_book\build\bench\hewiki_sandbox.db" `
  --seed-docs 6000 `
  --seed-lemmas 120000 `
  --lemma-batch-size 2000 `
  --save-cadence-ms 100 `
  --max-save-attempts 100 `
  --quick-check-timeout-sec 5

# Recreate sandbox again for after run
Copy-Item -Force `
  "J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db" `
  "J:\Project_Vibe\V_book\build\bench\hewiki_sandbox.db"

# Read-path baseline (after PATCH-01B)
.\.venv\Scripts\python.exe scripts\perf_harness.py `
  --db-path "J:\Project_Vibe\V_book\build\bench\hewiki_sandbox.db" `
  --runs 5 --warmup 1 `
  --out "build\bench\perf_baseline_after_patch01b.json"

# Write-gate contention baseline (after PATCH-01B)
.\.venv\Scripts\python.exe scripts\benchmark_import_concurrent_save.py `
  --db-path "J:\Project_Vibe\V_book\build\bench\hewiki_sandbox.db" `
  --seed-docs 6000 `
  --seed-lemmas 120000 `
  --lemma-batch-size 2000 `
  --save-cadence-ms 100 `
  --max-save-attempts 100 `
  --quick-check-timeout-sec 5
```

## Baseline Artifacts
- Read path (before): `build\bench\perf_baseline_before.json`
- Read path (after): `build\bench\perf_baseline_after_patch01b.json`
- Write benchmark (before): `build\logs\import_concurrent_save_metrics_20260306_050728.json`
- Write benchmark (after): `build\logs\import_concurrent_save_metrics_20260306_051447.json`
- Gate trace (before): `build\logs\import_write_gate_trace_20260306_050728.jsonl`
- Gate trace (after): `build\logs\import_write_gate_trace_20260306_051447.jsonl`

## Before (PATCH-01A)
### Read path p95
- dictionary_first_page: `0.002157s`
- dictionary_count: `0.130200s`
- picker_page_empty: `0.001613s`
- picker_page_search: `0.042700s`

### Write contention / gate telemetry
- import success: `true`
- import elapsed: `4.928s`
- save latency p95: `190.314ms`
- save latency max: `280.473ms`
- count >250ms: `1`
- gate max_hold_ms: `257.877ms`
- top phase max holds:
  - `import.table.source_document`: `257.877ms`
  - `import.table.lemma`: `230.898ms`
  - `import.table.library`: `58.844ms`

## Mitigation in PATCH-01B
- Change: route `import.table.source_document` through existing batch write-gate path (`_import_table_in_gate_batches`) instead of one long gate hold.
- Safety constraints preserved:
  - short WAL-safe write transactions,
  - deterministic ordered import flow,
  - cancellation checks between batches,
  - no UI-thread behavior changes.

## After (PATCH-01B)
### Read path p95
- dictionary_first_page: `0.002245s`
- dictionary_count: `0.157649s`
- picker_page_empty: `0.001652s`
- picker_page_search: `0.055216s`

### Write contention / gate telemetry
- import success: `true`
- import elapsed: `5.196s`
- save latency p95: `168.877ms`
- save latency max: `211.461ms`
- count >250ms: `0`
- gate max_hold_ms: `245.420ms`
- top phase max holds:
  - `import.table.lemma`: `245.420ms`
  - `import.table.source_document`: `157.890ms`
  - `import.table.document_text`: `59.413ms`

### Gate phase evidence for source_document
- Before: `1` release event (single long hold).
- After: `5` release events (batched holds).

## Before/After Delta (key)
- Primary metric (`import.table.source_document` max hold): `257.877ms -> 157.890ms` (`-99.987ms`, `-38.8%`).
- Secondary effect (concurrent save max latency): `280.473ms -> 211.461ms` (`-69.012ms`, `-24.6%`).
- Overall gate max hold: `257.877ms -> 245.420ms` (`-12.457ms`, `-4.8%`).

## Notes
- `PRAGMA quick_check(10)` in write benchmark timed out at `5s` and was treated as inconclusive by harness policy; `tm_entry` probe succeeded in both runs.
- No write-heavy benchmark operations targeted `M:\...`; all writes were against the local `J:\...` sandbox.

## PATCH-02 Planning (3-run stability, sandbox-only)
### Objective
- Re-measure post PATCH-01 state and confirm the next stable top write-gate bottleneck before coding PATCH-02.

### Commands used for stability scan
```powershell
Set-Location J:\Project_Vibe\V_book
New-Item -ItemType Directory -Force build\tmp | Out-Null
$tmp = (Resolve-Path build\tmp).Path
$env:TEMP = $tmp
$env:TMP = $tmp

1..3 | ForEach-Object {
  .\.venv\Scripts\python.exe scripts\benchmark_import_concurrent_save.py `
    --db-path "J:\Project_Vibe\V_book\build\bench\hewiki_sandbox.db" `
    --copy-target `
    --seed-docs 6000 `
    --seed-lemmas 120000 `
    --lemma-batch-size 2000 `
    --save-cadence-ms 100 `
    --max-save-attempts 100 `
    --quick-check-timeout-sec 5
}
```

### Stability artifacts (before PATCH-02)
- `build\logs\import_concurrent_save_metrics_20260306_053257.json`
- `build\logs\import_concurrent_save_metrics_20260306_053749.json`
- `build\logs\import_concurrent_save_metrics_20260306_054243.json`

### Stability finding
- Stable top bottleneck phase: `import.table.lemma` (`3/3` runs).
- Aggregate (`3-run`) before PATCH-02:
  - `overall_max_hold_ms`: max/p95 `336.019`, mean `250.024`
  - `lemma_phase_max_hold_ms`: max/p95 `336.019`, mean `250.024`
  - `save_p95_ms`: max/p95 `164.394`, mean `157.091`
  - `save_max_ms`: max/p95 `335.669`, mean `267.579`

## PATCH-02 Mitigation
- Single safe mitigation: add deterministic gate-batch cap for `lemma` write transactions during import.
- Implementation detail:
  - `HDLE_IMPORT_LEMMA_GATE_BATCH_CAP` (default `1500`) limits `lemma` write-gate batch size.
  - Existing configured `HDLE_IMPORT_LEMMA_BATCH_SIZE` remains the upper target; effective `lemma` batch = `min(batch_size, gate_cap)`.
- Safety:
  - no UI-thread changes,
  - deterministic order preserved,
  - chunked WAL-safe write transactions preserved,
  - cancel checks and cooperative yields preserved.

## PATCH-02 After (3-run)
### Artifacts
- `build\logs\import_concurrent_save_metrics_20260306_062342.json`
- `build\logs\import_concurrent_save_metrics_20260306_062835.json`
- `build\logs\import_concurrent_save_metrics_20260306_063324.json`

### Before vs After (3-run aggregate)
| Metric | Before max/p95 | After max/p95 | Delta (max/p95) | Before mean | After mean | Delta mean |
|---|---:|---:|---:|---:|---:|---:|
| overall_max_hold_ms | 336.019 | 275.991 | -60.028 | 250.024 | 270.934 | +20.910 |
| lemma_phase_max_hold_ms | 336.019 | 275.991 | -60.028 | 250.024 | 270.934 | +20.910 |
| save_max_ms | 335.669 | 307.853 | -27.816 | 267.579 | 281.957 | +14.378 |
| save_p95_ms | 164.394 | 174.271 | +9.877 | 157.091 | 172.032 | +14.941 |

### Interpretation
- Primary PATCH-02 goal achieved: worst-case `lemma` gate hold window reduced by ~`60ms` (`-17.9%`) on max/p95 tail.
- Tradeoff observed: average and p95 concurrent save latency increased; this is a follow-up target for PATCH-03.
