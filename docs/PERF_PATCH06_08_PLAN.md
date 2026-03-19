# PERF Plan: PATCH-06 .. PATCH-08 (Planning Only)

## Status
- This document records the agreed execution plan.
- Implementation scope in this planning step: **none**.
- `PATCH-05` is treated as partial baseline completion:
  - completed: `extract_terms`, `niqqud_bootstrap`, `translate_bootstrap`
  - deferred by operator: `tts_bootstrap` (cost-risk)

## Preconditions Before Real Schema/Index/Algorithm Optimization
1. Keep `M:\V_book\HDLE_Processing\hewiki_gpu_processing.db` strictly read-only for write-heavy operations.
2. Use only:
   - source copy: `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db`
   - sandbox write target: `J:\Project_Vibe\V_book\build\bench\hewiki_pipeline_sandbox.db` (with `--copy-target`)
3. Any single benchmark/test run must stay below 30 minutes.

## PATCH-06 (to implement first)
### Goal
Create pipeline-stage budget contract and deterministic checker for:
- `extract_terms`
- `niqqud_bootstrap`
- `translate_bootstrap`
- `tts_bootstrap` as deferred-aware stage

### Planned Files
- `docs/PERF_PIPELINE_BUDGET.md`
- `scripts/check_pipeline_stage_budget.py`
- `scripts/run_pipeline_perf_gate.ps1` (optional, low-risk)
- `tests/test_pipeline_stage_budget_checker.py`
- optional docs update: `docs/PROJECT_CONTRACT_GATES.md`

### Rules
- Thresholds must be evidence-based from existing successful pipeline artifacts.
- `tts_bootstrap` without baseline must be `DEFERRED/NOT_EVALUATED` and must not hard-fail overall status by default.
- Exit codes for checker:
  - `0` PASS
  - `2` WARN
  - `1` FAIL
- Fast Gate default behavior must remain unchanged (only env-gated optional integration).

## PATCH-07 (plan only)
### Goal
Add query-plan evidence pack for hot SQL paths (no runtime logic refactor).

### Planned Files
- `scripts/collect_queryplan_evidence.py` (name tentative)
- `docs/PERF_QUERYPLAN_EVIDENCE.md`
- artifacts in `build/logs/queryplan_*`

### Scope
- Extract Terms path queries
- Dictionary/lemma list/search/sort queries
- Terms list/filter/search queries
- representative Translation Management queries

## PATCH-08 (plan only)
### Goal
Add correctness harness so performance changes cannot silently break semantics.

### Planned Files
- `docs/PERF_CORRECTNESS_HARNESS.md`
- fast invariant checks/scripts/tests for bounded slice

### Scope
- Extract Terms invariants
- Niqqud overwrite/path invariants
- Translate overwrite/counter invariants
- TTS: deferred-safe correctness block until baseline is enabled

## Recommended Execution Order
1. Implement and ship `PATCH-06`.
2. Run bounded checks and keep each run below 30 minutes.
3. Implement `PATCH-07` (evidence only).
4. Implement `PATCH-08` (correctness guardrail).
5. Only then begin schema/index/algorithm optimization patches.

## Rollback Policy
- One commit per patch.
- Rollback command pattern:
  - `git revert --no-edit <PATCH_COMMIT_SHA>`
  - `git push origin main`
