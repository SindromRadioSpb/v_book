# Pipeline Stage Budget Contract (PATCH-06)

## Purpose
- Standardize PASS/WARN/FAIL for real pipeline stages (not only import write-gate).
- Keep Variant A unchanged by default: pipeline perf gate is optional unless explicitly enabled.
- Preserve deterministic, bounded evidence flow before schema/index/algorithm optimization patches.

## Scope
- Artifact source: `scripts/benchmarks/bench_reference_pipeline.py`
- Artifact family: `build\logs\pipeline_bench_metrics_*.json`
- Evaluation tool: `scripts/check_pipeline_stage_budget.py`
- Optional gate runner: `scripts/run_pipeline_perf_gate.ps1`

Stages:
- `extract_terms`
- `niqqud_bootstrap`
- `translate_bootstrap`
- `tts_bootstrap` (deferred-aware)

## Metric Definitions (per stage)
- `stage_name`
- `total_duration_ms`
- `throughput_rows_per_sec`
- `processed_count`
- `success_count`
- `error_count`
- `overwrite_mode`
- `chunk_size` / `batch_size` (if available in config)
- `first_error_samples` (up to 5)
- `artifact_paths`
- Optional DB/write-gate fields (if present in artifact):
  - `write_gate_overall_max_hold_ms`
  - `write_gate_overall_p95_hold_ms`
  - `write_gate_wait_ms`
- Optional cloud fields (if present in details):
  - `retry_count`
  - `rate_limit_hits`
  - `api_calls_count`
  - `avg_items_per_request`

## Baseline Source (evidence)
- `docs/PERF_PIPELINE_BASELINE_2026-03-06.md`
- Successful staged bounded baselines used:
  - `extract_terms`: `pipeline_bench_metrics_20260306_191129.json`
  - `niqqud_bootstrap`: `pipeline_bench_metrics_20260306_193418.json`
  - `translate_bootstrap`: `pipeline_bench_metrics_20260306_205757.json`
- `tts_bootstrap`: baseline deferred by operator due cost-risk.

## Threshold Derivation Rules (evidence-based)
For evaluated stages (`extract_terms`, `niqqud_bootstrap`, `translate_bootstrap`):
- Duration (lower is better):
  - PASS if `duration_ms <= baseline * 1.30`
  - WARN if `duration_ms <= baseline * 1.60`
  - FAIL otherwise
- Throughput (higher is better):
  - PASS if `throughput >= baseline * 0.80`
  - WARN if `throughput >= baseline * 0.60`
  - FAIL otherwise
- Processed count (higher is better):
  - PASS if `processed_count >= baseline * 0.90`
  - WARN if `processed_count >= baseline * 0.70`
  - FAIL otherwise
- Errors:
  - PASS if `error_count == 0`
  - FAIL otherwise

For `tts_bootstrap`:
- status is `DEFERRED / NOT_EVALUATED` by default until baseline evidence is explicitly approved.
- Deferred stage must not auto-fail overall status.

## Numeric Contract

### `extract_terms` (baseline: duration=100075ms, throughput=106.73, processed=10681)
| Metric | PASS | WARN | FAIL |
|---|---:|---:|---:|
| `total_duration_ms` | `<=130097.5` | `<=160120.0` | `>160120.0` |
| `throughput_rows_per_sec` | `>=85.384` | `>=64.038` | `<64.038` |
| `processed_count` | `>=9612.9` | `>=7476.7` | `<7476.7` |
| `error_count` | `==0` | n/a | `>0` |

### `niqqud_bootstrap` (baseline: duration=120565ms, throughput=16.59, processed=2000)
| Metric | PASS | WARN | FAIL |
|---|---:|---:|---:|
| `total_duration_ms` | `<=156734.5` | `<=192904.0` | `>192904.0` |
| `throughput_rows_per_sec` | `>=13.272` | `>=9.954` | `<9.954` |
| `processed_count` | `>=1800` | `>=1400` | `<1400` |
| `error_count` | `==0` | n/a | `>0` |

### `translate_bootstrap` (baseline: duration=975312ms, throughput=0.06, processed=60)
| Metric | PASS | WARN | FAIL |
|---|---:|---:|---:|
| `total_duration_ms` | `<=1267905.6` | `<=1560499.2` | `>1560499.2` |
| `throughput_rows_per_sec` | `>=0.048` | `>=0.036` | `<0.036` |
| `processed_count` | `>=54` | `>=42` | `<42` |
| `error_count` | `==0` | n/a | `>0` |

### `tts_bootstrap`
- `DEFERRED / NOT_EVALUATED` until approved baseline is captured.

## Stage and Overall Status Rules
- Stage status = worst metric status for that stage.
- Overall status:
  - PASS: all evaluated stages PASS
  - WARN: at least one evaluated stage WARN and no FAIL
  - FAIL: at least one evaluated stage FAIL
- Deferred stages are reported but excluded from FAIL-by-default logic.

## Canonical Commands
Use existing artifacts:
```powershell
cd /d J:\Project_Vibe\V_book
.\.venv\Scripts\python.exe scripts\check_pipeline_stage_budget.py `
  --take 20 `
  --glob "build/logs/pipeline_bench_metrics_*.json"
```

Optional one-command gate wrapper:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_pipeline_perf_gate.ps1
```

## Artifacts
- Input metrics: `build\logs\pipeline_bench_metrics_*.json`
- Checker report: `build\logs\pipeline_budget_report_latest.md`
- Optional gate runner log: `build\logs\pipeline_perf_gate_latest.log`

## Variant A Policy
- Fast Gate remains required for dev/PATCH workflow.
- Pipeline perf gate is optional by default.
- Optional integration may be enabled with `HDLE_ENABLE_PIPELINE_PERF_GATE=1`.
- Exit handling:
  - `0` PASS
  - `2` WARN (informational, may continue)
  - `1` FAIL

