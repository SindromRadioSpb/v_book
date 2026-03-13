# Audio Add-All Dialog First-Usable-State Repair (2026-03-13)

## Why this document exists

This document records the bounded runtime repair that was opened by:

- `docs/AUDIO_ADD_ALL_DIALOG_COLD_AUDIT_2026-03-13.md`

This repair stays narrow:

- it changes only the Add-All dialog document-selection and estimate-open path;
- it preserves queue population semantics and the existing add modes;
- it does not change schema, playlists, history, or audio generation paths;
- it does not reopen Coverage, TM, Sentences, startup, picker, or heavy-validation branches.

## Patch scope

Code changes:

- `app/services/document_service.py`
- `app/ui/workers.py`
- `app/ui/widgets/audio_player_panel.py`
- `tests/test_audio_add_all_dialog.py`

Bounded implementation:

- `ProjectDocumentsPageWorker` now supports optional project-scoped `status_filter`;
- `AddAllToQueueDialog` no longer eagerly loads the full processed-document list on open;
- processed-document search is now on-demand, remote, and limited to the first `200` results;
- search results are staged:
  - rows arrive first;
  - total count arrives later;
- selected document IDs persist across multiple searches;
- the dialog estimate remains explicitly approximate:
  - all-doc sentence estimate now uses `SUM(source_document.sentence_count)`;
  - selected-doc estimate uses cached per-document `sentence_count` metadata;
- queue population remains exact:
  - `AudioQueuePopulateWorker` still resolves sentence IDs from `document_sentence`;
- dialog close now cancels any in-flight project-document worker.

## Evidence artifacts

- `build/logs/cold_audit/audio_add_all_dialog/audio_add_all_dialog_probe.json`
- `build/logs/cold_audit/audio_add_all_dialog/audio_add_all_dialog_ui_probe.json`
- `build/logs/cold_audit/audio_add_all_dialog/audio_add_all_dialog_query_plan.json`
- `build/logs/cold_audit/audio_add_all_dialog/audio_add_all_dialog_cold_audit_summary.json`
- `build/logs/cold_audit/audio_add_all_dialog/audio_add_all_dialog_repair_after.json`
- `build/logs/cold_audit/audio_add_all_dialog/audio_add_all_dialog_repair_summary.json`

Approved target:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`
- access mode: strict read-only for the after-repair probe

Safety evidence:

- `audio_add_all_dialog_repair_after.json` records `db_mtime_unchanged=true`;
- no write path was introduced in the dialog repair;
- search probes and estimate probes ran only through read-only access.

## Before / after summary

Before the repair, the audit wave recorded:

- project list load: `0.019s`
- processed-document query for `project_id=1`: `0.818s`
- exact sentence estimate for `project_id=1`: `18.499s`
- offscreen dialog init: `48.989s`
- dialog-open doc list materialization: `387,639` rows

After the repair:

- offscreen dialog init: `0.238s`
- dialog-open doc list materialization: `0` rows
- approximate all-doc sentence total: `13,387,860`
- approximate all-doc estimate query time: `0.032s`
- representative processed-document search (`wiki`) page query: `0.226s`
- representative processed-document search (`wiki`) total count: `0.110s`
- representative processed-document search rows returned: `11`

Engineering meaning:

- the original blocker was the open-time contract, not the queue engine;
- the dialog now becomes usable without waiting for:
  - a `387,639`-row widget materialization;
  - an `18.499s` exact sentence count;
- the estimate is now intentionally approximate at open time, which is honest
  because the label already uses `~`;
- queue population semantics remain exact after the dialog is accepted.

## Current classification

Current status after the repair:

- `first usable state blocker`: closed
- `recommended priority`: `P0` closed
- `current residual tail`: none promoted on the approved target
- `open immediate second patch`: no

Decision logic:

- the approved-target open blocker is gone;
- processed-document search is now user-driven and no longer on the cold-open path;
- the remaining search/count timings observed on the approved target are not a
  new blocker for this dialog;
- exact queue semantics were preserved in the worker, while the dialog estimate
  remains an approximate planning aid.

## Branch and roadmap effect

This repair closes the active Audio Add-All dialog `P0` branch.

What remains closed:

- startup cold-path branch
- picker cold-path branch
- Sentences filtered-tail branch
- Dictionary search/FTS branch
- Terms cold-path branch
- Concordance dependency-health branch
- TM residual count-tail branch
- Coverage lemma-count residual-tail branch

What stays decision-gated:

- any future audio search/count follow-up for this dialog
- any broader audio queue UX redesign
- any queue/playlists/history write-path refactor

The next active engineering action is therefore:

- return to the canonical cold-audit framework for the next narrow subsystem wave,
  unless new approved-target evidence promotes a new audio blocker

## Repeatability commands

```powershell
New-Item -ItemType Directory -Force build\tmp\pytest | Out-Null
$env:TEMP = (Resolve-Path build\tmp\pytest).Path
$env:TMP = $env:TEMP
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m pytest tests\test_audio_add_all_dialog.py tests\test_audio_player_panel_dock_state.py tests\test_audio_queue_populate_worker.py tests\test_document_picker_flow.py -q
```

Import smoke:

```powershell
.\.venv\Scripts\python.exe -c "import app; from app.ui.widgets.audio_player_panel import AddAllToQueueDialog, AudioPlayerPanel; from app.ui.workers import ProjectDocumentsPageWorker, AudioQueuePopulateWorker; print('OK')"
```

The canonical artifacts to compare or review are:

- `build/logs/cold_audit/audio_add_all_dialog/audio_add_all_dialog_repair_after.json`
- `build/logs/cold_audit/audio_add_all_dialog/audio_add_all_dialog_repair_summary.json`
- `build/logs/cold_audit/audio_add_all_dialog/audio_add_all_dialog_probe.json`
- `build/logs/cold_audit/audio_add_all_dialog/audio_add_all_dialog_query_plan.json`
