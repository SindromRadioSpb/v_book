# Write-Gate Performance Budget Contract (PATCH-04)

## Purpose
- Standardize PASS/WARN/FAIL evaluation for write-gate contention benchmarks.
- Remove subjective interpretation from scaling patch evidence.
- Keep Variant A unchanged by default: perf gate is optional unless explicitly enabled.

## Scope
- Benchmark source: `scripts/benchmark_import_concurrent_save.py`
- Artifact family: `build\logs\import_concurrent_save_metrics_*.json`
- Evaluation tool: `scripts/check_write_gate_budget.py`
- Optional runner: `scripts/run_write_gate_perf_gate.ps1`

## Metric Definitions
- `overall_max_hold_ms`: per-run maximum write-gate hold from `gate_trace.max_hold_ms`.
- `lemma_phase_max_hold_ms`: per-run max hold for `phase=import.table.lemma`.
- `save_p95_ms`: per-run `save_ops.latency_ms.p95`.
- `save_max_ms`: per-run `save_ops.latency_ms.max`.

For each metric, checker computes aggregate across selected runs:
- `mean`
- `p95`
- `max`

## Threshold Derivation (evidence-based)
- Baseline source: `docs/PERF_BASELINE_REF_2026-03-06.md` (PATCH-03 AFTER aggregate).
- Baseline values used:
  - `overall_max_hold_ms` max/p95 = `278.947`
  - `lemma_phase_max_hold_ms` max/p95 = `278.947`
  - `save_p95_ms` max/p95 = `190.623`
  - `save_max_ms` max/p95 = `297.981`

PASS thresholds are derived exactly as:
- `overall_hold_p95_pass = baseline_after_overall_hold_p95 + 20ms`
- `overall_hold_max_pass = baseline_after_overall_hold_max + 40ms`
- `lemma_hold_p95_pass = baseline_after_lemma_hold_p95 + 20ms`
- `lemma_hold_max_pass = baseline_after_lemma_hold_max + 40ms`
- `save_p95_pass = baseline_after_save_p95 + 25ms`
- `save_max_pass = baseline_after_save_max + 40ms`

WARN band rule (per threshold):
- `warn_limit = pass_limit + max(30ms, 10% of pass_limit)`

FAIL rule:
- value `> warn_limit`

## Numeric Contract
| Check | PASS <= | WARN <= | FAIL > |
|---|---:|---:|---:|
| `overall_hold_p95_ms` | 298.947 | 328.947 | 328.947 |
| `overall_hold_max_ms` | 318.947 | 350.842 | 350.842 |
| `lemma_hold_p95_ms` | 298.947 | 328.947 | 328.947 |
| `lemma_hold_max_ms` | 318.947 | 350.842 | 350.842 |
| `save_p95_ms` | 215.623 | 245.623 | 245.623 |
| `save_max_ms` | 337.981 | 371.779 | 371.779 |

## Canonical Commands
### Produce 3-run artifacts (sandbox-only, no `M:\`)
```powershell
cd /d J:\Project_Vibe\V_book
1..3 | % {
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

### Evaluate selected artifacts
```powershell
.\.venv\Scripts\python.exe scripts\check_write_gate_budget.py `
  --take 3 `
  --glob "build/logs/import_concurrent_save_metrics_*.json"
```

### Optional one-command perf gate runner
```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_write_gate_perf_gate.ps1
```

## Artifacts and Evidence
- Bench artifacts: `build\logs\import_concurrent_save_metrics_*.json`
- Checker report: `build\logs\write_gate_budget_report_latest.md`
- Optional runner log: `build\logs\write_gate_perf_gate_latest.log`

Attach the following in PATCH DoD evidence:
- Selected 3 artifact filenames
- Checker report
- Final checker status and exit code

## Variant A Policy
- Fast Gate (`scripts/run_fast_gates.ps1`) remains the mandatory dev gate.
- Perf gate is optional by default.
- Perf gate is only invoked from Fast Gate when `HDLE_ENABLE_PERF_GATE=1`.
- With perf gate enabled:
  - checker exit `0` -> PASS
  - checker exit `2` -> WARN (Fast Gate continues with warning)
  - checker exit `1` -> FAIL (Fast Gate fails)
