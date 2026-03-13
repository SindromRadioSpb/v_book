# Coverage Panel First-Usable-State Repair (2026-03-13)

## Why this document exists

This document records the bounded runtime repair that was opened by:

- `docs/COVERAGE_PANEL_COLD_AUDIT_2026-03-13.md`

This repair stays narrow:

- it changes the Coverage worker / panel staging contract only;
- it preserves current coverage semantics;
- it does not change schema or write paths;
- it does not widen into historical P2 docs cleanup, TM/search work, or heavy
  validation.

## Patch scope

Code changes:

- `app/ui/workers.py`
- `app/ui/coverage_panel.py`
- `tests/test_coverage_panel_staged_loading.py`

Bounded implementation:

- `CoverageWorker` now emits fast comparison layers before lemma coverage;
- cluster coverage and both untranslated lists are now computed first;
- `CoverageWorker` emits:
  - `partial_ready(dict)` for fast panel state
  - `lemma_metrics_ready(CoverageMetrics)` for the slow exact metric
  - legacy `results_ready(dict)` after lemma metrics for compatibility
- `CoveragePanel` now renders the fast state before lemma coverage completes;
- the panel applies a request-sequence stale-drop guard;
- refresh requests are queued while a worker is already active;
- panel cancel now prefers `cancel()` and keeps `terminate()` as close-only
  fallback;
- lemma coverage query shape is unchanged in this repair.

## Evidence artifacts

- `build/logs/cold_audit/coverage_panel/coverage_panel_probe.json`
- `build/logs/cold_audit/coverage_panel/coverage_panel_query_plan.json`
- `build/logs/cold_audit/coverage_panel/coverage_panel_cold_audit_summary.json`
- `build/logs/cold_audit/coverage_panel/coverage_panel_repair_after.json`
- `build/logs/cold_audit/coverage_panel/coverage_panel_repair_summary.json`

Approved target:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`
- access mode: strict read-only for the audit and after-repair probes

Safety evidence:

- `coverage_panel_repair_after.json` records `db_mtime_unchanged=true`;
- no query-shape write path was introduced;
- no schema or data mutation was required for this repair.

## Before / after summary

Before the repair, the audit wave recorded:

- panel first usable state was blocked behind the full one-shot worker;
- full read-only service probe did not complete within `600s`;
- raw exact covered-lemma count did not complete within `120s`;
- fast comparison layers were already small:
  - lemma total count: `0.073s`
  - term-cluster coverage: `0.068s`
  - untranslated lemmas top `100`: `0.185s`
  - untranslated term clusters top `100`: `0.068s`

After the repair:

- stage-1 partial-ready state now arrives in `0.391s`;
- stage-1 breakdown:
  - cluster coverage: `0.118s`
  - untranslated lemmas top `100`: `0.197s`
  - untranslated term clusters top `100`: `0.077s`
- panel contract after repair:
  - cluster metrics render before lemma metrics
  - untranslated lists render before lemma metrics
  - panel no longer waits for terminal `results_ready(dict)` before becoming
    usable
- stage-2 tail remains:
  - exact lemma coverage total
  - query shape unchanged in this repair

Engineering meaning:

- this repair does not make lemma exact count fast;
- it removes lemma exact count from the first usable Coverage panel state;
- the original `P0` blocker was the combination of one-shot UI gating and the
  slow lemma exact-count path, and the first-usable-state part is now repaired.

## Current classification

Current status after the repair:

- `first usable state blocker`: closed
- `recommended priority`: `P0` closed
- `current residual tail`: exact lemma coverage total
- `open immediate second patch`: no

Decision logic:

- users can now see useful Coverage panel state without waiting for the slowest
  lemma metric;
- cluster coverage and untranslated lists were already fast and now surface as
  the first usable state;
- exact lemma coverage remains a real residual tail, but it is no longer the
  panel-open blocker;
- any second Coverage patch would be about residual exact-count work, not this
  first usable state defect.

## Branch and roadmap effect

This repair closes the active Coverage panel `P0` branch.

What remains closed:

- startup cold-path branch
- picker cold-path branch
- Sentences filtered-tail branch
- Dictionary search/FTS branch
- Terms cold-path branch
- Concordance dependency-health branch
- TM residual count-tail branch
- heavy-validation branches

What stays decision-gated:

- any second Coverage patch for exact lemma coverage total
- any broader metrics semantics redesign
- any historical P2 docs cleanup beyond status alignment

The next active engineering action is therefore:

- return to the canonical cold-audit framework for the next narrow subsystem
  wave, unless new approved-target evidence promotes the residual Coverage tail
  into a new blocker

## Repeatability commands

```powershell
New-Item -ItemType Directory -Force build\tmp\pytest | Out-Null
$env:TEMP = (Resolve-Path build\tmp\pytest).Path
$env:TMP = $env:TEMP
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m pytest tests\test_coverage_panel_staged_loading.py tests\test_workspace_navigation_v2.py tests\test_p1_workspace.py -q
```

Import smoke:

```powershell
.\.venv\Scripts\python.exe -c "import app; from app.ui.coverage_panel import CoveragePanel; from app.ui.workers import CoverageWorker; print('OK')"
```

The canonical artifacts to compare or review are:

- `build/logs/cold_audit/coverage_panel/coverage_panel_repair_after.json`
- `build/logs/cold_audit/coverage_panel/coverage_panel_repair_summary.json`
- `build/logs/cold_audit/coverage_panel/coverage_panel_probe.json`
- `build/logs/cold_audit/coverage_panel/coverage_panel_query_plan.json`
