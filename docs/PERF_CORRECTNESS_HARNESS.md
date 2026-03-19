# Perf Correctness Harness (PATCH-08)

## Purpose
- Protect semantics while performance changes are introduced.
- Catch "faster but wrong" regressions early on a bounded deterministic evidence set.
- Keep checks fast (minutes), without long full-scale runs.

## Scope
- Checker script: `scripts/check_perf_correctness_harness.py`
- Inputs: pipeline benchmark artifacts (`build\logs\pipeline_bench_metrics_*.json`)
- Output report: `build\logs\perf_correctness_report_latest.md`

## Stage Coverage
- `extract_terms`
- `niqqud_bootstrap`
- `translate_bootstrap`
- `tts_bootstrap` as deferred-safe stage

## Invariant Checks
### Common (all evaluated stages)
- `overall_status == pass`
- `stage_status == ok`
- `error_count == 0`
- `overwrite_mode == 1`
- `rows_total > 0`
- DB paths in artifact are not on `M:\`

### Extract Terms
- lemma rows > 0
- term rows > 0
- sentence rows > 0

### Niqqud
- lemma rows > 0
- sentence rows > 0
- `details.lexical.failed == 0` (or WARN if details missing)
- `details.sentence.failed == 0` (or WARN if details missing)

### Translate
- per-scope counters are consistent:
  - `total == succeeded + skipped + failed`
- if `total > 0`, then `failed == 0`
- if details are absent, stage goes WARN (not immediate FAIL)

### TTS
- default mode: `DEFERRED` and excluded from fail-by-default overall result.
- may be promoted to evaluated stage when approved baseline and cost policy are available.

## Status and Exit Codes
- Stage status: worst check status (`PASS` / `WARN` / `FAIL`)
- Overall status:
  - PASS if all evaluated stages PASS
  - WARN if any evaluated stage WARN and no FAIL
  - FAIL if any evaluated stage FAIL
- Deferred stage does not fail overall by default.

Exit codes:
- `0` = PASS
- `2` = WARN
- `1` = FAIL

## Canonical Command
```powershell
cd /d J:\Project_Vibe\V_book
.\.venv\Scripts\python.exe scripts\check_perf_correctness_harness.py `
  --take 20 `
  --glob "build/logs/pipeline_bench_metrics_*.json"
```

## Bounded Runtime Policy
- The harness consumes existing artifacts.
- No cloud calls, no write-heavy pipeline execution inside this checker.
- Intended for rapid local/CI validation before and after perf patches.
