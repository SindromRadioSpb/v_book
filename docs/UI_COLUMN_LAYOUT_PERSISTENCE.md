# UI Column Layout Persistence (Dictionary / Terms / Documents / Term Cards / Translation Memory)

**Status:** COMPLETE  
**Date:** 2026-02-17  
**Manual smoke-check:** PASS (confirmed after implementation)

## Scope

This update adds premium-grade column layout UX for:

1. `Dictionary` (`app/ui/dictionary_view.py`)
2. `Terms` (`app/ui/terms_view.py`)
3. `Documents` (`app/ui/documents_view.py`)
4. `Term Cards` (`app/ui/term_card_view.py`)
5. `Translation Memory` / TM Panel (`app/ui/translation_management_panel.py`)

## What is now guaranteed

1. User can resize any visible column manually (interactive header).
2. User can reorder columns via drag-and-drop header.
3. Column layout persists across sessions.
4. Right-click on table header shows `Reset Columns Layout`.
5. Reset returns each table to safe default widths.

## Implementation contract

Shared controller:

- `app/ui/table_layout_controller.py`

Responsibilities:

1. Apply interactive resize mode and movement support.
2. Restore saved header state using `SettingsService`.
3. Persist header state on resize/move with debounce (no write spam).
4. Save immediately on view close.
5. Validate restore against a schema signature (column count + header labels) to avoid bad restore after schema/UI changes.

## Settings keys

Per table:

- `table/<table_id>/header_state` (QHeaderView state)
- `table/<table_id>/header_signature` (column schema signature)

Table IDs used:

1. `dictionary_view`
2. `terms_view`
3. `documents_view`
4. `term_card_view`
5. `tm_panel`

## Regression-risk notes

1. `TM panel` previously could restore header state and then overwrite widths with fixed `setColumnWidth(...)`.
2. This conflict is removed: defaults apply only when restore is unavailable/incompatible.
3. Existing sorting, pagination, and inline-edit behavior remains unchanged.

## Verification

Automated:

- `tests/test_table_layout_controller.py`
- `tests/test_p1_settings.py`

Manual smoke matrix (executed):

1. Resize multiple columns in each of 5 target views.
2. Switch tabs and reopen app.
3. Verify widths/order restored.
4. Use header context menu -> `Reset Columns Layout`.
5. Verify reset to default layout in each view.

Result: PASS.
