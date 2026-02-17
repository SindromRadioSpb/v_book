# User Dictionaries (P0)

## Access

- Global workspace: `Premium -> User Dictionaries` or `Ctrl+Shift+U`.
- Project workspace: open any project and switch to `User Dictionaries` tab.

## Key Behavior

- Add rows from `Dictionary`, `Terms`, `Term Cards`, and `Translation Management`.
- Dedupe inside each dictionary by canonical hash.
- `Hide Noise` is enabled by default.
- Translation is resolved from `tm_global`, not copied into dictionary items.

## Scope

- Scope chip: `Current Project` / `All`.
- Default scope: `Current Project` when opened from project context, otherwise `All`.
- Active scope is shown as `Filtered by: ...`, and `Show All` is available for quick reset.

## Translate Selected

- Uses the same batch translate dialog modes:
  - `Fill empty only`
  - `Overwrite existing`
  - `Skip non-empty`
- Uses progress UX `BatchProgressDialogV3`.
- Runs in background worker with cancel/pause/resume.
- Writes canonical translation to `tm_global` and propagates to linked `tm_entry`.

## Deep Link

- `User Dictionaries` header includes `Open Translation Management`.
- `Translation Management` header includes `Open User Dictionaries`.

## Audio Column (P0)

- `Audio` column shows `missing|ready|failed` from `audio_asset`.
- No generation/playback in P0.
