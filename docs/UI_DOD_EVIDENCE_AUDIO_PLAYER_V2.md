# UI DoD Evidence - Audio Player v2

Task: 25/26 - Audio Player v2 (Premium)
Last verified against code/tests: 2026-02-24

## Definition of Done checklist

### Functional status

- [x] Non-destructive queue (items stay after playing).
- [x] Queue table columns include rich source context (`Project`, `Document`, `Source ID`).
- [x] Playlist entries table has matching rich source context columns.
- [x] Queue/Playlist column visibility toggles are persisted separately in QSettings.
- [x] Queue/Playlist header state (width/order) is persisted separately in QSettings.
- [x] Runtime speed (`0.25x..4.0x`) + persistence.
- [x] Repeat modes (`Off|One|All`) + repeat count.
- [x] Auto-pause and gap controls.
- [x] Add All worker with SQL chunking and V3 progress.
- [x] Add All path resolution + unresolved-track upgrade on rerun.
- [x] Queue display batch refresh for Niqqud/Translation/Source.
- [x] Playlist display batch refresh for Niqqud/Translation/Source/Project/Document.
- [x] Queue -> Playlist via header button + context menu.
- [x] Queue -> Playlist premium picker (search/create/dedup/add mode/preview).
- [x] Playlists entry playback works (`Play`, `Play Selected`, row `▶`, double click).
- [x] Playlist keyboard actions work (`Enter/Space` play selected, `Del` remove selected).
- [x] `Load to Queue` is explicit replace-flow with confirmation.
- [x] `Add to Queue` appends playlist entries without destructive reset.
- [x] History tab is DB-backed in panel UI (`audio_history` binding).
- [x] History rows support `Play Selected`, row `▶`, row double-click and `Add to Queue`.
- [x] `Go to Source` uses active tab row (`Queue/Playlists/History`) for routing payload.

### Safety status

- [x] No long operation in UI thread for Add All.
- [x] Worker uses V3 progress signal contract.
- [x] Path safety for audio asset resolution (relative-only, no traversal).
- [x] Existing source-table playback semantics remain enqueue-first.
- [x] Playlist refresh errors are non-fatal and logged as warnings.

## Manual smoke matrix (task_26)

1. Open panel (`Ctrl+Alt+L`), verify Queue/Playlists tabs visible.
2. In Queue, select rows and click `Add to Playlist...`; confirm premium picker opens.
3. In picker: search playlist, create new playlist inline, choose dedup on, add mode `Append`, click Add.
4. Repeat add for same rows; confirm duplicates are skipped by `(project_id, kind, source_id)`.
5. In Playlists, click `Play`; ensure playback starts from playlist rows without clearing Queue.
6. In Playlists, select one row and click `Play Selected`; only selected row starts.
7. Click row `▶` in Playlist `Status`; selected entry plays.
8. Double-click playlist row; row plays.
9. Click `Add to Queue`; entries append to Queue and existing queue remains.
10. Click `Load to Queue`; confirm replace prompt appears; on Yes queue is replaced.
11. Click Playlist `↻`; verify Niqqud/Translation/Source/Project/Document refresh.
12. Change Queue column visibility via gear; restart app; visibility restores.
13. Change Playlist column visibility via gear; restart app; visibility restores.
14. Resize/reorder Queue and Playlist columns; restart app; header layout restores.
15. In Playlist entries table, press `Enter` and `Space`; selected rows are played.
16. In Playlist entries table, press `Del`; selected rows are removed.
17. Play one row and open `History`; confirm new DB row is visible without app restart.
18. In `History`, select one row and click `Go to Source`; target project tab opens and row is focused.
19. In `Playlists`, select one row and click `Go to Source`; target source row is focused.
20. In `Queue/Playlists/History`, select multiple rows; `Go to Source` is disabled.

## Action policy table (PATCH-06 contract)

`Queue` tab:
- Selection `0`: `Go to Source` follows current playing row (if exists), `Add to Playlist` disabled.
- Selection `1` + status `ready`: `Play from here` enabled, `Go to Source` enabled if source payload exists.
- Selection `1` + status `missing/stale/generating/failed`: `Play from here` disabled in context menu; clicking status cell shows safe message.
- Selection `>1`: `Go to Source` disabled.

`Playlists` tab:
- `Play` enabled only when selected playlist contains at least one `ready` row.
- `Play Selected` enabled only when current selection contains at least one `ready` row.
- `Go to Source` enabled only for single selected row with valid source payload.
- `Move up/down` enabled only for single row and valid boundary.

`History` tab:
- `Play Selected` enabled only when selection contains at least one `ready` row.
- `Add to Queue` enabled on non-empty selection.
- `Go to Source` enabled only for single selected row with valid source payload.

Shared rules:
- Multi-select always disables `Go to Source`.
- Missing/Stale/Generating/Failed never fail silently:
  - status-cell click and explicit play attempts emit clear status-bar guidance.

## Automated evidence references

- `tests/test_audio_player_playlists_playback.py`
- `tests/test_audio_player_queue_add_to_playlist.py`
- `tests/test_audio_player_playlist_columns_persistence.py`
- `tests/test_audio_player_playlist_display_refresh.py`
- `tests/test_audio_player_playlists_panel.py`
- `tests/test_audio_player_nondestructive.py`
- `tests/test_audio_player_queue_engine.py`
- `tests/test_audio_track_source_url.py`
- `tests/test_audio_queue_service.py`
- `tests/test_audio_queue_display_resolver.py`
- `tests/test_audio_queue_populate_worker.py`
- `tests/test_audio_player_panel_dock_state.py`
- `tests/test_audio_player_rate.py`
- `tests/test_audio_player_repeat.py`
- `tests/test_audio_player_history_panel.py`
- `tests/test_audio_player_action_policy.py`
- `tests/test_audio_player_user_safe_messages.py`

## Open premium backlog (next slice)

- Persisted queue resume between sessions (product decision).

## Screenshot/log checklist

- Queue header: `Add to Playlist...`, `↻`, gear menu.
- Premium Queue->Playlist picker dialog (search/dedup/add mode preview).
- Playlist entries with row `▶` and rich source columns.
- Playlist playback started from selected entry without queue reset.
- Queue and Playlist gear toggles persisted after restart.
- Playlist `↻` refresh updating Niqqud/Translation/Source context.
- History tab with DB rows and `Go to Source` from selected history row.
- Missing/Stale status-cell click showing safe user message in status bar.
