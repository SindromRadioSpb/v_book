# Documents View First-Usable-State Repair (2026-03-13)

## Why this document exists

This document records the bounded runtime repair that was opened by:

- `docs/DOCUMENTS_VIEW_COLD_AUDIT_2026-03-13.md`

This repair stays narrow:

- it changes only the Documents view NLP-engine readiness contract;
- it preserves async documents paging and snapshot readiness loading;
- it does not change schema, document queries, or NLP processing semantics;
- it does not reopen Audio, Coverage, TM, Sentences, picker, startup, or
  heavy-validation branches.

## Patch scope

Code changes:

- `app/ui/workers.py`
- `app/ui/documents_view.py`
- `tests/test_documents_engine_readiness.py`
- `tests/test_documents_pagination_sort_search.py`
- `tests/test_documents_delete_flow.py`

Bounded implementation:

- `NLPEngineReadinessWorker` now probes optional `stanza` / `torch` capability
  in a background thread;
- `DocumentsView.init_ui()` no longer imports NLP dependencies in the UI thread;
- the view now opens with a staged readiness label:
  - `Checking NLP engine readiness...`
  - documents paging starts immediately;
- `Process with NLP` and `Re-process` stay disabled while engine readiness is
  still unknown;
- once the worker completes, the view updates:
  - engine status label
  - GPU checkbox visibility
  - process/re-process button tooltips and enabled state
- direct process/re-process entry points also guard against readiness still
  being in flight;
- close now cooperatively stops the engine-readiness worker.

## Evidence artifacts

- `build/logs/cold_audit/documents_view/documents_view_init_full.json`
- `build/logs/cold_audit/documents_view/documents_view_init_without_engine_checks.json`
- `build/logs/cold_audit/documents_view/documents_view_cold_audit_summary.json`
- `build/logs/cold_audit/documents_view/documents_view_repair_after.json`
- `build/logs/cold_audit/documents_view/documents_view_repair_summary.json`

Approved target:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`
- access mode: strict read-only for the after-repair probe

Safety evidence:

- `documents_view_repair_after.json` records `db_mtime_unchanged=true`;
- the repair introduces no new write path;
- the after probe used a read-only DB wrapper while instantiating `DocumentsView`.

## Before / after summary

Before the repair, the audit wave recorded:

- full `DocumentsView` cold open: `2.300s`
- same path without engine checks: `0.063s`
- isolated engine-check delta: `2.237s`
- documents page after async worker completion:
  - `25` rows
  - `387,639` total documents

After the repair:

- `DocumentsView` init returns in `0.077s`
- first page becomes visible in `0.376s`
- NLP engine readiness finishes later in `2.045s`
- the view opens with:
  - documents table active
  - status `Loading documents...`
  - engine label `Checking NLP engine readiness...`
- after background work completes:
  - first page reaches `25 / 387,639`
  - engine label becomes `Stanza engine available (GPU: No)`

Engineering meaning:

- the old blocker was the open-time contract, not the async documents page;
- the repair removes optional NLP dependency imports from the first usable state
  critical path;
- the Documents surface is now usable before the heavy readiness probe finishes;
- engine readiness remains accurate, but it is now stage-2 UI work.

## Current classification

Current status after the repair:

- `first usable state blocker`: closed
- `recommended priority`: `P0` closed
- `current residual tail`: none promoted on the approved target
- `open immediate second patch`: no

Decision logic:

- the approved-target blocker was synchronous capability probing in
  `DocumentsView.init_ui()`;
- that work now happens off the UI thread;
- the main user-visible path is open and useful before the NLP readiness result
  returns;
- no Documents SQL redesign or NLP semantics change is justified from this
  repair alone.

## Branch and roadmap effect

This repair closes the active Documents view `P0` branch.

What remains closed:

- startup cold-path branch
- picker cold-path branch
- Sentences filtered-tail branch
- Dictionary search/FTS branch
- Terms cold-path branch
- Concordance dependency-health branch
- TM residual count-tail branch
- Coverage lemma-count residual-tail branch
- Audio Add-All branch

What stays decision-gated:

- any future Documents residual-tail work
- any documents SQL redesign
- any broader NLP-processing workflow redesign

The next active engineering action is therefore:

- return to the canonical cold-audit framework for the next narrow subsystem wave,
  unless new approved-target evidence promotes a new Documents blocker

## Repeatability commands

```powershell
New-Item -ItemType Directory -Force build\tmp\pytest | Out-Null
$env:TEMP = (Resolve-Path build\tmp\pytest).Path
$env:TMP = $env:TEMP
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m pytest tests\test_documents_engine_readiness.py tests\test_documents_pagination_sort_search.py tests\test_documents_snapshot_readiness_ui.py tests\test_documents_delete_flow.py tests\test_documents_process_progress_ui.py -q
```

Import smoke:

```powershell
.\.venv\Scripts\python.exe -c "import app; from app.ui.documents_view import DocumentsView; from app.ui.workers import NLPEngineReadinessWorker; print('OK')"
```

The canonical artifacts to compare or review are:

- `build/logs/cold_audit/documents_view/documents_view_repair_after.json`
- `build/logs/cold_audit/documents_view/documents_view_repair_summary.json`
- `build/logs/cold_audit/documents_view/documents_view_cold_audit_summary.json`
