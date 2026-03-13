# Project View First-Usable-State Repair (2026-03-13)

## Why this document exists

This document records the bounded runtime repair that was opened by:

- `docs/PROJECT_VIEW_COLD_AUDIT_2026-03-13.md`

This repair stays narrow:

- it changes only the hidden `Term Cards` load contract during project open;
- it preserves the existing default `Documents` tab and child-tab set;
- it does not change schema, Term Cards semantics, or broader workspace routing;
- it does not reopen Documents, Audio, Coverage, TM, Sentences, picker,
  startup, or heavy-validation branches.

## Patch scope

Code changes:

- `app/ui/project_view.py`
- `app/ui/term_card_view.py`
- `tests/test_project_view_deferred_term_cards.py`

Bounded implementation:

- `TermCardView` now accepts `defer_initial_load=True`;
- when deferred, the queue is not loaded in `__init__()`;
- `TermCardView.ensure_review_queue_loaded()` loads the review queue once on
  first actual tab activation;
- `ProjectView` now creates hidden `TermCardView` with deferred load enabled;
- `ProjectView` activates the queue only when:
  - the user opens the `Term Cards` tab;
  - code explicitly focuses `term_cards`;
- no broad lazy-tab framework was introduced.

## Evidence artifacts

- `build/logs/cold_audit/project_view/project_view_probe.json`
- `build/logs/cold_audit/project_view/project_view_cold_audit_summary.json`
- `build/logs/cold_audit/project_view/project_view_repair_after.json`
- `build/logs/cold_audit/project_view/project_view_repair_summary.json`

Approved target:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`
- access mode: strict read-only for the after-repair probe

Safety evidence:

- `project_view_repair_after.json` records `db_mtime_unchanged=true`;
- no write path was introduced in the repair;
- the after probe stayed bounded to project open plus first `Term Cards`
  activation on a read-only DB wrapper.

## Before / after summary

Before the repair, the audit wave recorded:

- full `ProjectView` cold open: `1.627s`
- shell-only `ProjectView`: `0.071s`
- `ProjectView` with only `TermCardView` real: `1.593s`
- standalone `TermCardView` cold open: `1.553s`
- current visible tab after open: `Documents`

After the repair:

- full `ProjectView` cold open: `0.442s`
- current visible tab after open remains `Documents`
- hidden `Term Cards` queue loaded on open: `false`
- hidden `Term Cards` status on open:
  - `Review queue loads when tab is opened`
- first explicit `Term Cards` activation: `1.197s`
- `Term Cards` queue rows after activation: `760`
- first active card position after activation: `1 / 760`

Engineering meaning:

- the old blocker was hidden eager `Term Cards` work on the project-open path;
- project open is now dominated by the visible workspace shell, not by a hidden
  review queue;
- the repair removes hidden queue load from the first usable state critical
  path without changing the tab set or project routing;
- standalone `Term Cards` first activation remains a separate residual tail,
  not a still-open project-open blocker.

## Current classification

Current status after the repair:

- `first usable state blocker`: closed
- `recommended priority`: `P0` closed
- `current residual tail`:
  - standalone `Term Cards` first activation (`1.197s` on the approved target)
- `open immediate second patch`: no

Decision logic:

- the approved-target blocker was hidden `TermCardView.load_review_queue()`
  running during sync project open;
- that work is now deferred until the tab is actually opened;
- the visible `Documents` entry path stays intact and becomes usable much
  earlier;
- the remaining `Term Cards` activation cost is now decision-gated and should
  not reopen a new branch without separate evidence.

## Branch and roadmap effect

This repair closes the active ProjectView `P0` branch.

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
- Documents view branch

What stays decision-gated:

- any future standalone `Term Cards` activation optimization
- any broad lazy-tab framework for ProjectView
- any broader workspace shell redesign

The next active engineering action is therefore:

- return to the canonical cold-audit framework for the next narrow subsystem
  wave, unless new approved-target evidence promotes a new ProjectView or
  standalone `Term Cards` blocker

## Repeatability commands

```powershell
New-Item -ItemType Directory -Force build\tmp\pytest | Out-Null
$env:TEMP = (Resolve-Path build\tmp\pytest).Path
$env:TMP = $env:TEMP
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m pytest tests\test_project_view_deferred_term_cards.py tests\test_workspace_app_window_contract.py tests\test_p1_workspace.py tests\test_p1_layout_persistence.py tests\test_term_card_audio_context_menu.py tests\test_term_card_last_review_visuals.py tests\test_term_card_table_model.py -q
```

Import smoke:

```powershell
.\.venv\Scripts\python.exe -c "import app; from app.ui.project_view import ProjectView; from app.ui.term_card_view import TermCardView; print('OK')"
```

The canonical artifacts to compare or review are:

- `build/logs/cold_audit/project_view/project_view_repair_after.json`
- `build/logs/cold_audit/project_view/project_view_repair_summary.json`
- `build/logs/cold_audit/project_view/project_view_cold_audit_summary.json`
