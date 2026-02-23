# Audio Player v2 - Implementation Requirements (Approved)

Date: 2026-02-23  
Status: Approved for implementation

## Objective

Bring Audio Player panel to professional premium level with minimal regression risk.

This roadmap is authoritative for the next iteration and must be used before coding.

## Mandatory preflight (before implementation)

1. Read and align with current contracts/docs:
- `docs/AUDIO_PLAYER_V2.md`
- `docs/AUDIO_PLAYER_V2_AUDIT.md`
- `docs/UI_DOD_EVIDENCE_AUDIO_PLAYER_V2.md`
- `docs/AUDIO_ASSET_ARCH.md`
- `task_25.md`
- `task_25.4.md`
- `task_25.5.md`

2. Confirm in code (no guessing):
- `app/ui/widgets/audio_player_panel.py`
- `app/services/audio_player_service.py`
- `app/services/audio_queue_service.py`
- `app/services/audio_playback_service.py`
- `app/ui/workers.py`
- `app/ui/dialogs/batch_progress_dialog_v3.py`
- `app/infra/migrations/025_audio_player_v2.sql`

3. Preconditions must remain true:
- no long ops in UI thread,
- Add All remains SQL chunked + worker + V3 progress,
- queue display refresh remains batch (no per-row SQL),
- path safety and WAL-safe short transactions remain intact.

## Blind spots to close before coding

1. Decide queue-to-DB sync policy for playback stats in panel:
- when exactly `mark_played()` is committed,
- UI refresh strategy after DB update.

2. Finalize navigation contract for `Go to Source`:
- route resolution (`sentences|dictionary|terms`),
- behavior when row/source no longer exists.

3. Scope-lock for PATCH-05 actions:
- first ship minimum stable set,
- keep unsupported kinds/actions disabled in UI.

## Approved patch plan

### PATCH-01 - Contract freeze and implementation guardrails
Files:
- `docs/AUDIO_PLAYER_V2_AUDIT.md`
- `docs/UI_DOD_EVIDENCE_AUDIO_PLAYER_V2.md`
- `docs/AUDIO_PLAYER_V2.md`

Steps:
1. Freeze in-scope/out-of-scope for current iteration.
2. Lock risk zones and non-functional constraints.
3. Keep acceptance matrix explicit.

### PATCH-02 - Go to Source + DB play stats sync
Files:
- `app/ui/widgets/audio_player_panel.py`
- `app/services/audio_queue_service.py`
- `app/ui/app_window.py` (if routing bridge required)

Steps:
1. Wire `Go to Source` through `resolve_source_link()`.
2. On track completion, persist queue play stats (`play_count`, `last_played_at`).
3. Refresh queue model deterministically after commit.

### PATCH-03 - Queue context actions (worker-safe)
Files:
- `app/ui/widgets/audio_player_panel.py`
- `app/ui/workers.py`
- existing translate/niqqud/audio services (reuse only)

Steps:
1. Add context actions:
- Translate Selected
- Niqqudize Selected
- Regenerate Audio
- Edit Pronunciation
- Edit Sentence Niqqud
2. Run heavy actions only in workers.
3. Use `BatchProgressDialogV3` for long ops with cancel.
4. Update stale/status/snapshots after completion.

### PATCH-04 - Playlists tab DB wiring
Files:
- `app/ui/widgets/audio_player_panel.py`
- `app/services/audio_queue_service.py`

Steps:
1. Replace placeholder with entries table.
2. Wire create/rename/delete/load/add/remove/reorder.
3. Keep atomic short transactions.

### PATCH-05 - History tab DB wiring
Files:
- `app/ui/widgets/audio_player_panel.py`
- `app/services/audio_queue_service.py`

Steps:
1. Bind panel history view to `audio_history`.
2. Add refresh behavior and clear source indication.

### PATCH-06 - Hardening + UX polish + docs evidence
Files:
- `app/ui/widgets/audio_player_panel.py`
- `docs/UI_DOD_EVIDENCE_AUDIO_PLAYER_V2.md`
- `docs/KEYBOARD_SHORTCUTS.md` (if changed)

Steps:
1. Action enablement/disablement by row kind/status.
2. Safe user feedback for missing/stale/unavailable rows.
3. Final smoke matrix and evidence update.

## Test plan

### New tests
- `tests/test_audio_player_go_to_source.py`
- `tests/test_audio_player_db_play_sync.py`
- `tests/test_audio_player_queue_context_actions.py`
- `tests/test_audio_player_queue_context_workers.py`
- `tests/test_audio_player_playlists_panel.py`
- `tests/test_audio_player_history_panel.py`

### Mandatory regression suite
- `python -m pytest tests/test_audio_player_nondestructive.py tests/test_audio_track_source_url.py tests/test_audio_queue_display_resolver.py tests/test_audio_queue_populate_worker.py -q`
- `python -m pytest tests/test_audio_player_queue_engine.py tests/test_audio_player_rate.py tests/test_audio_player_repeat.py tests/test_audio_player_panel_dock_state.py -q`
- `python -m pytest tests/test_audio_queue_service.py tests/test_audio_player_history.py -q`
- `python -m pytest tests/test_security.py tests/test_project_exchange.py -q`

## Definition of Done

Functional:
1. Queue context actions work from Audio Player without UI freeze.
2. `Go to Source` opens correct origin row/view.
3. Play stats are synced and visible (`Plays`, `Last played`).
4. Playlists tab is fully DB-backed in panel UI.
5. History tab is DB-backed in panel UI.

Non-functional:
1. Add All remains worker-only, chunked, V3 progress.
2. No per-row SQL in queue display refresh.
3. Path safety and WAL-safe write behavior preserved.

Docs/Evidence:
1. `docs/UI_DOD_EVIDENCE_AUDIO_PLAYER_V2.md` updated with smoke proof.
2. Remaining limitations list is accurate and explicit.

## Commit plan (implementation phase)

1. `feat(audio-player): wire go-to-source and persist play stats`
2. `feat(audio-player): add queue context actions via worker-safe flows`
3. `feat(audio-player): implement db-backed playlists tab UI`
4. `feat(audio-player): bind history tab to audio_history service`
5. `chore(audio-player): harden queue actions and refresh evidence`
