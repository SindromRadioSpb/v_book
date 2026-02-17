# Audio Asset Architecture (P0 Stub)

## Scope

P0 introduces storage and lookup contracts only. Audio generation and playback are out of scope.

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

- `User Dictionaries` has `Audio` column.
- Status resolved in bulk via `AudioAssetService.bulk_get_status(...)`.
- Default shown status: `missing`.
