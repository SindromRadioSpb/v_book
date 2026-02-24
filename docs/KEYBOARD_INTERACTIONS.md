# Keyboard Interaction Patterns

This document describes keyboard interaction contracts for premium UX.

## SRCH-03 Keyboard Flow (Sidebar Project Search)

Actions:

- Focus sidebar search field.
- Use `Up` / `Down`.
- Use `Enter`.
- Use `Esc`.

Expected:

- Arrow keys move selected result row.
- `Enter` opens selected project.
- `Esc` clears search text.

## A11Y-01 Keyboard Tab Flow (Sidebar)

Actions:

- Navigate sidebar with `Tab` / `Shift+Tab`.

Expected:

- Focus moves through all visible controls.
- No focus traps between search input/list and main navigation controls.
- Focus order is deterministic across sessions.

## CMD-01 Command Palette

Actions:

- Open command palette with `Ctrl+P` (or layout-equivalent shortcut).
- Type a query.
- Navigate with arrows.
- Execute with `Enter`.

Expected:

- Query filters actions without UI freeze.
- First result is auto-selected.
- `Enter` executes selected action.

## TM-KEY-01 Scope and Navigation

Actions:

- Open Translation Management via shortcut.
- Toggle scope chips and verify status label.

Expected:

- Scope label changes to `Filtered by: ...`.
- Project picker is disabled in `Current Project` mode.

## UD-KEY-01 Review/Browse Controls

Actions:

- Open User Dictionaries.
- Move through controls with keyboard.
- Trigger table actions for selected rows.

Expected:

- Selection-bound actions become enabled only when rows are selected.
- Keyboard navigation keeps focus visible and predictable.
