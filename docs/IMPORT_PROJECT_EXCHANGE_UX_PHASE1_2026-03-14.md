# Import / Project Exchange UX Phase 1 (2026-03-14)

## Goal

Deliver a bounded product-facing improvement on the existing `.hdleproj` import
path without reopening cold-hunt, lower-layer recovery, or a broad import
redesign.

## Implemented in this wave

- added a real read-only preflight summary against the current host DB before
  import starts
- surfaced host/bundle schema compatibility in the preview dialog
- surfaced current name-conflict handling and auto-rename outcome in the preview
  dialog
- surfaced total row count and pronunciation metadata summary in the preview
  dialog
- fixed import success details so the completion report is visible
- made `Go to Project` actually navigate to the imported project after success

## Files

- `app/services/project_exchange/dto.py`
- `app/services/project_exchange/import_engine.py`
- `app/ui/dialogs/project_exchange_dialogs.py`
- `app/ui/app_window.py`
- `tests/test_project_exchange_preflight.py`
- `tests/test_project_exchange_dialogs.py`
- `tests/test_workspace_app_window_contract.py`

## Out of scope

- side-by-side conflict review
- incremental import
- import history
- new schema work
- broad import/export redesign
- generic performance work

## Decision gate after this wave

If further work continues in this area, choose explicitly between:

- richer import review UX
- release-facing validation hardening
- or stopping here and preserving the current bounded improvement
