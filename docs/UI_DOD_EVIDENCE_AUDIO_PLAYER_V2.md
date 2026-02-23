# UI DoD Evidence - Audio Player v2

Task: 25 - Audio Player v2 (Premium)  
Last verified against code/tests: 2026-02-23

## Definition of Done checklist

### Functional status

- [x] Non-destructive queue (items stay after playing).
- [x] Queue table columns: Hebrew, Niqqud, Translation, Source, Status, Plays.
- [x] Column visibility toggles with QSettings persistence.
- [x] Runtime speed control (`0.25x..4.0x`) + persistence.
- [x] Repeat modes (`Off|One|All`) + repeat count.
- [x] Auto-pause and gap controls.
- [x] Previous/Next/Stop transport controls + hotkeys.
- [x] Add All worker with SQL chunking and V3 progress.
- [x] Add All path resolution + unresolved-track upgrade on rerun.
- [x] Queue display batch refresh for Niqqud/Translation/Source.
- [x] Direct-play rows initialize `Plays=0` (no `-`).
- [x] Clicked row play in source tables appends and starts clicked item immediately.
- [ ] Queue context actions: Translate/Niqqudize/Regen/Edit Pronunciation/Edit Sentence Niqqud.
- [ ] Go to Source navigation wiring.
- [ ] Full playlist CRUD table UI in panel.
- [ ] DB-backed history binding in panel UI.
- [ ] DB `play_count`/`last_played_at` sync from panel playback completion.

### Safety status

- [x] No long operation in UI thread for Add All flow.
- [x] Worker uses V3 progress signal contract.
- [x] Path safety for audio asset resolution (relative-only, no traversal).
- [x] Existing source-table playback entrypoints keep backward compatibility.

## Manual smoke matrix (current iteration)

1. Open panel with `Ctrl+Alt+L`; dock appears and can be hidden/shown.
2. Add 3 rows from any source table with `Play Audio Selected`; queue shows all 3 and keeps them after playback.
3. Click row play in source table while queue already has items; clicked row starts immediately and is appended to queue.
4. Run Add All for a project source; verify V3 progress updates and final summary dialog.
5. After Add All completion, verify new rows are playable when ready audio exists.
6. Verify queue `Status` does not show false `ready` for unresolved sentinel rows.
7. Verify Niqqud/Translation/Source are populated after automatic batch refresh (or manual refresh button).
8. Verify `Plays` starts at `0` and increments after playback finishes.
9. Change speed during playback; verify audible rate change and persistence after restart.
10. Verify repeat cycling (`R`) and repeat count behavior.
11. Verify auto-pause pauses after each item.
12. Verify context menu currently includes only play/remove/copy actions (expected current scope).

## Automated evidence references

- `tests/test_audio_player_nondestructive.py`
- `tests/test_audio_track_source_url.py`
- `tests/test_audio_queue_display_resolver.py`
- `tests/test_audio_queue_populate_worker.py`
- `tests/test_audio_player_queue_engine.py`
- `tests/test_audio_player_panel_dock_state.py`
- `tests/test_audio_player_rate.py`
- `tests/test_audio_player_repeat.py`
- `tests/test_audio_queue_service.py`

## Open premium backlog (next slice)

- PATCH-05 context actions from queue rows with worker-safe execution.
- Deep-link `Go to Source` handler.
- Playlist tab DB CRUD and entry table.
- History tab DB history binding.
- Persisted queue resume between sessions (optional, product decision).

## Screenshot/log checklist

- Queue with current-row highlight and row play delegate.
- Add All source picker + V3 progress + completion summary.
- Queue after Add All with non-empty Niqqud/Translation/Source columns.
- Runtime speed/repeat/auto-pause controls in panel.
- Manual refresh (`↻`) updating queue display context.
