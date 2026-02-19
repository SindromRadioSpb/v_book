# Audio Asset Architecture (P0 Stub)

## Scope

P0 includes source-audio generation pipeline with mock providers and persistent asset storage.

Hard rule:

- Audio is generated for `source` text only (`src_text` / canonical `src_norm`).
- Translation text is not used for TTS generation.

## Table

`audio_asset` key:

- `(lang, norm_text, voice_id, speed, provider)` unique

Main fields:

- `asset_status`: `missing | ready | failed`
- `audio_rel_path`: relative path only (sanitized)
- `duration_ms`, `sha256`, `error_text`

## Security Rules

- Store relative paths only.
- Reject absolute paths, drive paths, and parent traversal (`..`).
- Keep SQL parameterized.

## UI

- `User Dictionaries`, `Dictionary`, `Terms`, `Term Cards`, and `Translation Management` expose `Audio` status column.
- Status is resolved in bulk via `AudioAssetService.bulk_get_status_any(...)`.
- Default shown status: `missing`.

## Generation Flow (P0)

- Entry point: `User Dictionaries` -> `Generate Audio...` (toolbar or context menu).
- Additional entry points:
  - `Dictionary` -> `Generate Audio...` / `Generate Audio Selected (N rows)...`
  - `Terms` -> `Generate Audio...` / `Generate Audio Selected (N rows)...`
  - `Term Cards` -> `Generate Audio...` / `Generate Audio Selected (N rows)...`
  - `Translation Management` -> `Generate Audio...` / `Generate Audio Selected (N rows)...`
- Long operation runs in `UserDictGenerateAudioWorker` with `BatchProgressDialogV3` (cancel/pause/resume).
- Cross-view selected-row flow uses `BatchGenerateAudioWorker` with the same `BatchProgressDialogV3` contract.
- Provider mode:
  - `chain` (recommended)
  - `force:<provider_id>`
- Write mode:
  - `MISSING_ONLY`
  - `REGENERATE_ALL`

## Playback UX

- `Play Audio` action is available for selected rows in:
  - `User Dictionaries`
  - `Dictionary`
  - `Terms`
  - `Term Cards`
  - `Translation Management`
- Playback opens first ready asset among selected rows via OS default player.
- If no ready audio exists, UI shows a non-fatal hint to run `Generate Audio...`.
