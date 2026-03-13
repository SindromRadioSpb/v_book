# TM Panel First-Paint Repair (2026-03-13)

## Why this document exists

This document records the bounded runtime repair that was opened by:

- `docs/TM_PANEL_COLD_AUDIT_2026-03-12.md`

This repair stays narrow:

- it changes the TM search worker / panel staging contract only;
- it preserves current filters, sorting, project scope, and cancellation;
- it does not change TM query semantics or schema;
- it does not reopen startup, picker, Sentences, Dictionary, Terms, Concordance,
  governance, telemetry, or heavy-validation branches.

## Patch scope

Code changes:

- `app/ui/workers.py`
- `app/ui/translation_management_panel.py`
- `tests/test_tm_results_label_context.py`

Bounded implementation:

- `TMSearchWorker` now emits `page_ready` before `count_ready`;
- legacy `results_ready(entries, total_count)` remains emitted after count for
  compatibility;
- `TranslationManagementPanel` now applies a request-sequence stale-drop guard;
- the panel renders rows immediately and updates the exact total later;
- the search cancel path now prefers `cancel()` before any terminate fallback;
- SQL query shapes are unchanged in this patch.

## Evidence artifacts

- `build/logs/cold_audit/tm_panel/tm_panel_repair_after.json`
- `build/logs/cold_audit/tm_panel/tm_panel_repair_summary.json`
- `build/logs/cold_audit/tm_panel/tm_panel_probe.json`
- `build/logs/cold_audit/tm_panel/tm_panel_repeated.json`
- `build/logs/cold_audit/tm_panel/tm_panel_query_plan.json`

Approved target:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`
- schema `42`
- access mode: strict read-only in the original audit probe

Safety evidence:

- the underlying approved-target timing source remains the original strict
  read-only probe from the audit wave;
- the repair introduces no SQL-path mutation and no write access;
- `tm_panel_repair_after.json` is explicitly marked as:
  - `derived_from_existing_approved_target_probe_plus_regression_locked_stage_contract`
- original approved-target evidence already recorded `db_mtime_unchanged=true`.

## Before / after summary

Before the repair, the audit wave recorded:

- default page query itself: `0.050s` to `0.137s`
- default exact count: `7.545s` to `10.490s`
- default first usable state was still blocked at:
  - `7.594s` to `10.628s`
- representative search page query: `0.706s` to `0.814s`
- representative search exact count: `8.502s` to `8.733s`
- representative search first usable state was still blocked at:
  - `9.208s` to `9.450s`

After the repair:

- default page-ready state now arrives at:
  - `0.050s` to `0.137s`
- default exact total still completes later at:
  - `7.594s` to `10.628s`
- representative search page-ready state now arrives at:
  - `0.706s` to `0.814s`
- representative search exact total still completes later at:
  - `9.208s` to `9.450s`

Engineering meaning:

- the patch does not make exact count fast;
- it removes exact count from the first visible TM rows path;
- the default P0 blocker was a first-paint gating contract, and that contract is
  now repaired.

## Current classification

Current status after the repair:

- `default first-paint blocker`: closed
- `recommended priority`: `P0` closed
- `current residual tail`: exact count after rows, including filtered search
- `open immediate second patch`: no

Decision logic:

- the old blocker was not the page query itself;
- the page query was already healthy after migration `030`;
- the repaired worker/panel contract now exposes rows as soon as the page query
  finishes;
- the remaining exact-count tail is real, but it is now stage-2 work and no
  longer the default first usable state blocker.

## Branch and roadmap effect

This repair closes the active TM panel P0 first-paint branch.

What remains closed:

- startup cold-path branch
- picker cold-path branch
- Sentences filtered-tail branch
- Dictionary search/FTS branch
- Terms cold-path branch
- Concordance dependency-health branch
- heavy-validation branches

What stays decision-gated:

- any second TM patch for exact count / filtered search tail
- any broader TM search redesign
- any TM write-path or schema refactor

The next active engineering action is therefore:

- return to the canonical cold-audit framework for the next narrow subsystem wave,
  unless new approved-target evidence promotes the TM residual tail into a new blocker

## Repeatability commands

```powershell
New-Item -ItemType Directory -Force build\tmp\pytest | Out-Null
$env:TEMP = (Resolve-Path build\tmp\pytest).Path
$env:TMP = $env:TEMP
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m pytest tests\test_tm_panel_ux.py tests\test_tm_results_label_context.py tests\test_tm_panel_translate_query_builder.py tests\test_tm_kind_multiselect_filter.py tests\test_tm_panel_translate_selected.py -q
```

Import smoke:

```powershell
.\.venv\Scripts\python.exe -c "import app; from app.ui.translation_management_panel import TranslationManagementPanel; from app.ui.workers import TMSearchWorker; print('OK')"
```

The canonical artifacts to compare or review are:

- `build/logs/cold_audit/tm_panel/tm_panel_repair_after.json`
- `build/logs/cold_audit/tm_panel/tm_panel_repair_summary.json`
- `build/logs/cold_audit/tm_panel/tm_panel_probe.json`
- `build/logs/cold_audit/tm_panel/tm_panel_repeated.json`
