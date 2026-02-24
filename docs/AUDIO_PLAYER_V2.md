# Audio Player v2 - Usage Guide

Task: 25/26 - Audio Player v2 (Premium)
Last verified against code: 2026-02-24

## Overview

Audio Player v2 is the in-app playback surface for Hebrew study flow:

- Non-destructive queue (items stay in queue after playback).
- Runtime playback controls (speed, repeat, auto-pause, gap, cadence presets).
- Add All flow with SQL chunking + worker + V3 progress dialog.
- Row-level play via delegate in `Status` column.
- Playlists tab supports direct entry playback (no manual copy to Queue).
- Queue and Playlist tables support rich source columns with persisted visibility/layout.

## Open the panel

- Menu: `View -> Toggle Audio Player`
- Shortcut: `Ctrl+Alt+L`
- Dock: bottom by default, resizable and dockable.

## Queue behavior (confirmed)

- Queue in `AudioPlayerService` is non-destructive (`_tracks` + `_current_index`).
- `Previous` (`J`) moves to prior queue item.
- Clicking row play in source tables appends to queue and starts that clicked item immediately.
- Queue -> Playlist flow is available directly from Queue:
  - header button `Add to Playlist...`
  - context action `Add selected to Playlist (...)`
- `Plays` starts at `0` for Add All rows and direct Play rows.
- `Plays` increments on each completed playback item.

## Add All behavior (confirmed)

- `Add All...` opens source picker (project, kind, sentence document filter, add mode).
- Population runs in `AudioQueuePopulateWorker` with `BatchProgressDialogV3`.
- No UI-selection expansion for all rows; IDs are fetched via SQL.
- New rows are synced to in-memory queue by `new_item_ids` only.
- Audio path binding uses:
  1. direct `audio_asset_id`,
  2. fallback by normalized `norm_text`.
- Existing unresolved duplicates are upgraded in place when possible.
- Display overlays (Niqqud / Translation / Source) are refreshed in batch after completion.

## Playback controls

Transport:

- `Space` play/pause
- `J` previous
- `K` next
- `Esc` stop (keep queue)

Runtime controls:

- Speed: `0.25x..4.0x`, persisted in `audio/playback/rate`.
- Repeat: `Off | One | All` plus repeat count for `One`.
- Auto-pause after each item.
- Gap between items (ms).
- Presets:
  - Normal `200/550/300`
  - Study `300/800/450`
  - Fast `100/250/120`

## Queue table

Columns:

- `#`, `Hebrew`, `Niqqud`, `Translation`, `Source`, `Status`, `Plays`, `Project`, `Document`, `Source ID`.

Column visibility + layout persistence:

- Toggle Queue columns via gear menu in panel header.
- Persisted keys:
  - `audio_player/queue/columns_visible`
  - `audio_player/queue/header_state`

Row visuals:

- Current row highlight (green).
- Stale row highlight (amber).

Queue context menu (current scope):

- Play from here
- Go to Source
- Remove from Queue
- Translate / Niqqudize / Regenerate Audio
- Add selected to Playlist
- Edit/Clear Translation
- Edit Pronunciation / Edit Sentence Niqqud
- Copy Hebrew / Niqqud / Translation

## Playlists tab

Implemented in-panel features:

- Create / rename / delete playlist.
- Add selected Queue rows via premium picker dialog:
  - playlist search,
  - inline create playlist,
  - dedup by `(project_id, kind, source_id)`,
  - add mode (`Append`, `Prepend`, `After selected entry`),
  - preview of new vs duplicate rows.
- Direct playback from Playlist entries:
  - `Play` (from first)
  - `Play Selected`
  - row `▶` delegate in `Status`
  - row double-click play
- `Add to Queue` appends entries (non-destructive).
- `Load to Queue` replaces queue only after explicit confirmation.
- Remove and reorder entries.
- Keyboard on Playlist entries table:
  - `Enter` / `Space` -> play selected entries.
  - `Del` (or `Backspace`) -> remove selected entries.
- Playlist display refresh (`↻`) for batch Niqqud/Translation/Source updates.

Playlist entries columns:

- `#`, `Hebrew`, `Niqqud`, `Translation`, `Source`, `Status`, `Project`, `Document`, `Source ID`.

Column visibility + layout persistence:

- Toggle Playlist columns via gear menu in playlist header.
- Persisted keys:
  - `audio_player/playlist/columns_visible`
  - `audio_player/playlist/header_state`

## History tab

- History table is DB-backed (`audio_history`) and loaded directly in panel UI.
- Controls:
  - `Play Selected` (enqueue mode).
  - `Add to Queue` (append selected history rows).
  - `↻` refresh (reload + batch context refresh).
- Row actions:
  - `▶` in `Status` column and row double-click to play.
  - Context menu with `Go to Source`, `Add selected to Queue`, copy actions.
- History columns:
  - `#`, `Hebrew`, `Niqqud`, `Translation`, `Source`, `Status`, `Played At`, `Rate`, `Project`, `Document`, `Source ID`.

## Current limitations (open items)

- `Go to Source` button may be unavailable for rows with insufficient source payload.
- No persisted queue restore on app restart in panel flow yet.

## Go to Source behavior

- `Go to Source` resolves payload from the active tab context:
  - Queue tab -> selected queue row (single selection), fallback to current track.
  - Playlists tab -> selected playlist row (single selection), fallback to current track.
  - History tab -> selected history row (single selection), fallback to current track.
- If multiple rows are selected in the active tab, button is disabled.

## Technical notes

- Runtime speed uses `QMediaPlayer.setPlaybackRate()` through `QtMultimediaBackend.set_rate()`.
- Generation speed in `audio_asset.speed` is independent from runtime playback rate.
- Queue state machine and cadence run in player service; long operations stay out of UI thread.
- Playlist display refresh is batch-based; per-row SQL is avoided.
