# User Dictionaries (P0)

## What It Is

`User Dictionaries` is a project tab for collecting study targets independent of table pagination and source view.

## Key Behavior

- Add rows from `Dictionary`, `Terms`, `Term Cards`, and `Translation Management`.
- Dedupe inside each dictionary by canonical hash.
- `Hide Noise` is enabled by default.
- Translation is shown from `tm_global`, not copied into dictionary items.

## Translate Selected

- Uses the same batch translate dialog modes:
  - `Fill empty only`
  - `Overwrite existing`
  - `Skip non-empty`
- Uses progress UX `BatchProgressDialogV3`.
- Runs in background worker with cancel/pause/resume.
- Writes canonical translation to `tm_global` and propagates to linked `tm_entry`.

## Audio Column (P0)

- `Audio` column shows `missing|ready|failed` from `audio_asset`.
- No generation/playback in P0.

## Manual Smoke

1. Open project -> `User Dictionaries`.
2. Create dictionary and add a manual item.
3. Add selected rows from `Dictionary` or `Terms` via context menu.
4. Run `Translate Selected...` and verify progress dialog counters.
5. Confirm translated text appears in `User Dictionaries` and linked `TM` rows.
