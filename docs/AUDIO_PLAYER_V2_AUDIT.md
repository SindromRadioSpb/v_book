# Audio Player v2 - Codebase Audit

Date: 2026-02-23  
Task: 25 - Audio Player v2 (Premium)

## 1) Entry points and architecture

Primary UI panel:

- `app/ui/widgets/audio_player_panel.py`
  - queue table model: `AudioQueueTableModel`
  - source picker dialog: `AddAllToQueueDialog`
  - panel widget: `AudioPlayerPanel`

Playback engine:

- `app/services/audio_player_service.py`
  - `AudioPlayerService` (singleton)
  - `AudioTrack`
  - `QtMultimediaBackend`

Queue/playlist/history persistence service:

- `app/services/audio_queue_service.py`
  - `AudioQueueService`
  - DTOs and source-link payload

Audio path resolver:

- `app/services/audio_playback_service.py`
  - `resolve_ready_path()` uses `updated_at DESC, asset_id DESC`
  - relative-path safety checks enforced

Add All worker:

- `app/ui/workers.py`
  - `AudioQueuePopulateWorker`
  - SQL ID collection + chunked insert
  - V3 progress signals

DB schema:

- `app/infra/migrations/025_audio_player_v2.sql`
  - `audio_queue_item`
  - `audio_playlist`
  - `audio_playlist_entry`
  - `audio_history`

## 2) Confirmed implemented behavior

Queue and playback:

- Non-destructive queue in `AudioPlayerService` (`_tracks` + `_current_index`).
- Runtime speed control wired to `QMediaPlayer.setPlaybackRate()`.
- Repeat modes (`none|one|all`) and repeat count.
- Auto-pause and gap between items.
- Delegate-based row play in queue `Status` column.

Recent bug-fix coverage already in tests:

- Add All unresolved sentinel (`Path("") -> "."`) correctly treated as `missing`.
- Add All rerun upgrades unresolved duplicate rows in place.
- Add All rows with ready assets become playable after DB-to-memory sync.
- Queue display batch refresh updates Niqqud/Translation/Source.
- Direct-play rows initialize `play_count=0` and increment on playback.
- Enqueue with explicit row play starts clicked appended item immediately.

## 3) Current panel limitations (confirmed in code)

- `Go to Source` button is present but not wired to navigation handler.
- Queue context menu currently includes only:
  - Play from here
  - Remove
  - Copy Hebrew/Niqqud/Translation
- Playlists tab is a shell (no entry table CRUD wiring in panel).
- History tab in panel is in-memory session list; DB history service is not yet wired there.
- Queue DB stats (`mark_played`) are not called by panel playback flow yet.

## 4) Regression-sensitive zones

- `_load_db_queue_to_player()` path resolution and dedup upgrade logic.
- `_refresh_display_contexts()` batch enrichment logic (must stay no per-row SQL).
- `play_paths(..., start_immediately=True)` semantics for row-click UX.
- Consistency between in-memory queue and persisted queue rows.

## 5) Existing automated coverage relevant to Audio Player

Core tests:

- `tests/test_audio_player_nondestructive.py`
- `tests/test_audio_player_queue_engine.py`
- `tests/test_audio_player_rate.py`
- `tests/test_audio_player_repeat.py`
- `tests/test_audio_track_source_url.py`
- `tests/test_audio_queue_display_resolver.py`
- `tests/test_audio_queue_populate_worker.py`
- `tests/test_audio_player_panel_dock_state.py`
- `tests/test_audio_queue_service.py`
- `tests/test_audio_player_history.py`

## 6) Recommended next implementation slice

Minimal-risk next slice for premium completion:

- Wire `Go to Source` using `AudioQueueService.resolve_source_link()`.
- Wire DB-backed `mark_played()` updates from playback completion.
- Promote playlists/history tabs from shell/session to DB-backed UI.
- Add PATCH-05 queue context actions via workers + V3 progress:
  - Translate
  - Niqqudize
  - Regenerate audio
  - Edit Pronunciation / Edit Sentence Niqqud
