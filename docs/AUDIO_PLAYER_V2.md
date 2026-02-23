# Audio Player v2 - Usage Guide

Task: 25 - Audio Player v2 (Premium)  
Last verified against code: 2026-02-23

## Overview

Audio Player v2 is now the in-app playback surface for Hebrew study flow:

- Non-destructive queue (items stay in queue after playback).
- Runtime playback controls (speed, repeat, auto-pause, gap, cadence presets).
- Queue table with user-togglable columns: Hebrew, Niqqud, Translation, Source, Status, Plays.
- Add All flow with SQL chunking + worker + V3 progress dialog.
- Row-level play via delegate in `Status` column.

## Open the panel

- Menu: `View -> Toggle Audio Player`
- Shortcut: `Ctrl+Alt+L`
- Dock: bottom by default, resizable and dockable.

## Queue behavior (confirmed)

- Queue is non-destructive (`AudioPlayerService._tracks` is not popped on play).
- Current row is represented by `_current_index`.
- `Previous` (`J`) moves back to prior queue item.
- Clicking row play in a source table appends to queue and starts that clicked item immediately.
- `Plays` starts at `0` for both:
  - DB-loaded Add All rows.
  - Direct `Play Audio` row actions from tables.
- `Plays` increments on each completed item playback.

## Add All behavior (confirmed)

- `Add All...` opens source picker (project, kind, document filter for sentences, add mode).
- Population runs in `AudioQueuePopulateWorker` with `BatchProgressDialogV3`.
- No UI selection expansion is used for all rows; IDs are fetched via SQL.
- After insertion:
  - rows are synced into in-memory queue by `new_item_ids` only,
  - resolved audio paths are bound using:
    1. direct `audio_asset_id`,
    2. fallback lookup by normalized `norm_text`,
  - existing unresolved duplicate tracks are upgraded in place.
- Display overlays (Niqqud / Translation / Source) are refreshed in batch right after completion.

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

- `#`, `Hebrew`, `Niqqud`, `Translation`, `Source`, `Status`, `Plays`.

Column visibility:

- Toggle via gear menu.
- Persisted to `audio_player/columns_visible`.

Row visuals:

- Current row highlight (green).
- Stale row highlight (amber).

Context menu (current scope):

- Play from here
- Remove from Queue
- Copy Hebrew / Copy Niqqud / Copy Translation

## Tabs

Queue:

- Fully functional table-based queue.

Playlists:

- UI shell exists.
- Full playlist entry table and CRUD wiring in panel are pending.

History:

- Session history list (last 200) is shown in panel.
- DB-backed history exists in service layer but is not yet bound to panel UI.

## Current limitations (open items)

- `Go to Source` button is visible but navigation wiring is pending.
- Queue context actions from Task 25 PATCH-05 are pending:
  - Translate/Niqqudize/Regen/Edit Pronunciation/Edit Sentence Niqqud.
- Playlist and history tabs in panel are not yet fully bound to DB service data.
- No persisted queue restore on app restart in panel flow yet.

## Technical notes

- Runtime speed uses `QMediaPlayer.setPlaybackRate()` through `QtMultimediaBackend.set_rate()`.
- Generation speed in `audio_asset.speed` is independent from runtime playback rate.
- Queue state machine and cadence run in the player service; no long operation runs in UI thread.
