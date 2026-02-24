# Audio Player v2 - Codebase Audit

Date: 2026-02-24
Task: 25/26 - Audio Player v2 (Premium)

## 1) Entry points and architecture

Primary panel:

- `app/ui/widgets/audio_player_panel.py`
  - Queue model: `AudioQueueTableModel`
  - Playlist entries model: `AudioPlaylistEntriesTableModel`
  - Queue -> Playlist picker: `AddQueueToPlaylistDialog`
  - Batch display refresh handlers:
    - `_refresh_display_contexts()` (Queue)
    - `_refresh_playlist_display_contexts()` (Playlists)

Playback engine:

- `app/services/audio_player_service.py`
  - non-destructive queue runtime (`_tracks`, `_current_index`)

Queue/playlist/history persistence:

- `app/services/audio_queue_service.py`
  - queue CRUD
  - playlist CRUD/reorder/load
  - `add_items_to_playlist(..., add_mode, dedup_by_source)`

Audio path resolver:

- `app/services/audio_playback_service.py`
  - `resolve_ready_path()` and safe relative path policy

Add All worker:

- `app/ui/workers.py`
  - `AudioQueuePopulateWorker` with V3 progress contract

## 2) Confirmed implemented behavior

- Queue remains non-destructive.
- Direct row play from source tabs appends and starts clicked row.
- Queue `Plays` starts at `0` and increments on complete playback.
- Queue -> Playlist works from Queue header button and Queue context menu.
- Queue -> Playlist premium dialog supports:
  - playlist search,
  - inline create,
  - dedup by `(project_id, kind, source_id)`,
  - add modes (`append/prepend/after_selected`),
  - add preview (`new` vs `duplicates`).
- Playlist entries are playable directly:
  - `Play`, `Play Selected`, row `▶`, and double click.
- Playlist entries support keyboard actions:
  - `Enter/Space` for play selected.
  - `Del` for remove selected.
- `Load to Queue` is explicit replace with confirmation.
- `Add to Queue` appends playlist entries.
- Queue and Playlist tables both support rich source columns and persisted toggles/header state.
- Playlist display refresh is batched and non-fatal on resolver errors.
- History tab is DB-backed in panel UI with batch context refresh.
- `Go to Source` resolves from active tab selection (`Queue/Playlists/History`).

## 3) Remaining limits (known)

- Persisted queue restore on app startup remains optional backlog.

## 4) Regression-sensitive zones

- `_load_db_queue_to_player()` path resolution + unresolved upgrade logic.
- `_refresh_display_contexts()`, `_refresh_playlist_display_contexts()`, `_refresh_history_display_contexts()` batching contracts.
- Queue/Playlist column visibility + header state persistence keys.
- Playlist playback path resolution (`_resolve_playlist_row_paths`) and safe path guard.

## 5) Automated coverage relevant to task_26

- `tests/test_audio_player_playlists_playback.py`
- `tests/test_audio_player_queue_add_to_playlist.py`
- `tests/test_audio_player_playlist_columns_persistence.py`
- `tests/test_audio_player_playlist_display_refresh.py`
- `tests/test_audio_player_playlists_panel.py`
- `tests/test_audio_queue_service.py`
- `tests/test_audio_queue_display_resolver.py`
- `tests/test_audio_player_nondestructive.py`
- `tests/test_audio_player_queue_engine.py`
- `tests/test_audio_player_rate.py`
- `tests/test_audio_player_repeat.py`
- `tests/test_audio_track_source_url.py`
- `tests/test_audio_player_history_panel.py`
