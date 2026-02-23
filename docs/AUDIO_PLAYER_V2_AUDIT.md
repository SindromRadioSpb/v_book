# Audio Player v2 — Codebase Audit

**Date:** 2026-02-23
**Task:** Task 25 — Audio Player v2 (Premium)

---

## 1. Current Audio Player UI

### `app/ui/widgets/audio_player_panel.py` (163 lines)

- **Class:** `AudioPlayerPanel(QWidget)` — compact dock widget
- **Queue display:** `QListWidget` (minimal label display only)
- **Controls:** Play/Pause, Stop, Next, Clear Queue buttons
- **Cadence presets:** Normal (200/550/300 ms), Study (300/800/450), Fast (100/250/120)
- **Hotkeys:** Space=play/pause (WidgetWithChildrenShortcut), Esc=stop
- **Settings persisted:** `audio/playback/pre_roll_ms`, `audio/playback/gap_ms`, `audio/playback/post_roll_ms`
- **Connects to:** `AudioPlayerService` signals: `queue_changed`, `now_playing_changed`, `playback_state_changed`, `playback_error`

**Gaps:**
- No speed control
- No column toggles
- No Hebrew/Niqqud/Translation display
- No history or playlists
- No context menu on queue items
- No "Add All Filtered" functionality
- Double-click: removes items before selected to jump to position (hacky)

### `app/ui/app_window.py` — Dock integration

- Dock: `audio_player_dock`, `Qt.DockWidgetArea.BottomDockWidgetArea`
- Action: `premium.audio_player`, title "Toggle Audio Player"
- Visibility persisted: QSettings `audio_player_dock_visible`

---

## 2. Audio Player Service

### `app/services/audio_player_service.py` (472 lines)

**`AudioTrack` dataclass (L40-55):**
```python
path: Path
label: str = ""
context: Dict[str, Any] = field(default_factory=dict)
```
Minimal — no source reference, no snapshot data, no play count.

**`AudioBackendBase` (L58-75):** Abstract interface — `play()`, `stop()`, `pause()`, `resume()`.
Signals: `finished`, `error`, `state_changed`.
**No `set_rate()` / `get_rate()` method.**

**`QtMultimediaBackend` (L78-137):**
- `QMediaPlayer` + `QAudioOutput`
- **`QMediaPlayer.setPlaybackRate(float)` exists in Qt6 API but is NEVER called**
- All methods: play, stop, pause, resume (= `_player.play()`)

**`AudioPlayerService` (L140-471):**
- Singleton via `get_instance()`
- Queue: `self._queue: Deque[AudioTrack]`
- **`_start_next_track()` → `self._queue.popleft()` — DESTRUCTIVE, items removed after playing**
- Cadence engine: `_pre_timer`, `_gap_timer`, `_post_timer` (QTimer, single-shot)
- `play_paths()` → enqueue mode or interrupt (clears + replays)
- No persistence (queue lost on restart)
- No repeat modes
- No `previous_track()`
- Settings read: `audio/playback/pre_roll_ms`, `gap_ms`, `post_roll_ms`, `play_mode`

---

## 3. Audio Playback Service

### `app/services/audio_playback_service.py` (142 lines)

- `resolve_ready_paths(session, items)` — queries `AudioAsset` for `asset_status='ready'`
- `launch_audio_files(paths, labels, play_mode)` — delegates to `AudioPlayerService.play_paths()`
- Fallback: OS-native player if internal backend unavailable

---

## 4. Views with Play Audio (all share same pattern)

| View | File | Method |
|------|------|--------|
| sentences_view | sentences_view.py | `_selected_audio_items()`, `_play_audio_items()`, `on_play_audio()`, `on_audio_cell_play_clicked()` |
| dictionary_view | dictionary_view.py | Same pattern |
| terms_view | terms_view.py | Same pattern |
| user_dictionaries_view | user_dictionaries_view.py | Same pattern |
| term_card_view | term_card_view.py | Same pattern |

**Common pattern:**
1. Build `items = [{"src_lang": ..., "src_norm": ..., "src_text": ...}]`
2. `resolve_ready_paths(session, items=items)`
3. `launch_audio_files(paths, labels, play_mode="enqueue"|"interrupt")`

---

## 5. TTS / Audio Cache Model

### `AudioAsset` ORM (sa_models.py L818-849)

| Column | Type | Notes |
|--------|------|-------|
| asset_id | INTEGER PK | |
| lang | TEXT | e.g. "he" |
| norm_text | TEXT | normalized source text |
| voice_id | TEXT | default="default" |
| speed | FLOAT | default=1.0 (pre-generated at speed, NOT runtime) |
| provider | TEXT | azure/google/elevenlabs/none |
| asset_status | TEXT | missing/ready/failed |
| audio_rel_path | TEXT | relative path in HDLE storage |
| duration_ms | INTEGER | |
| sha256 | TEXT | file hash |
| error_text | TEXT | failure reason |
| created_at / updated_at | TEXT | ISO UTC |

**Unique:** (lang, norm_text, voice_id, speed, provider)

> Note: `speed` in AudioAsset means the audio was TTS-generated at that speed. It is NOT runtime playback rate. Runtime rate control requires `QMediaPlayer.setPlaybackRate()`.

---

## 6. Edit Dialogs

| Dialog | File | Opens From |
|--------|------|-----------|
| `EditPronunciationDialog` | `edit_pronunciation_dialog.py` | dictionary_view.py, terms_view.py context menus |
| `EditSentenceNiqqudDialog` | `edit_sentence_niqqud_dialog.py` | sentences_view.py `on_edit_niqqud_selected()` |

Both are reusable — can be called from Audio Player context menu.

---

## 7. Workers

### Existing Audio Workers (workers.py)

- `UserDictGenerateAudioWorker` — generates TTS for user dictionary scope
- `BatchGenerateAudioWorker` — generates TTS for explicit item list

**V3 Signal contract (both):**
```python
progress = pyqtSignal(int, int)           # (completed, total)
stats_updated = pyqtSignal(int, int, int) # (succeeded, skipped, failed)
row_translated = pyqtSignal(str, str, bool)  # (entity_id, message, success)
stage_updated = pyqtSignal(str)
finished = pyqtSignal(dict)
error = pyqtSignal(str)
paused = pyqtSignal()
resumed = pyqtSignal()
```

---

## 8. BatchProgressDialogV3

### `app/ui/dialogs/batch_progress_dialog_v3.py`

**Public API for workers:**
- `update_progress(completed, total)` — progress bar + ETA
- `update_counts(succeeded, skipped, failed)` — counters
- `add_recent_item(entity_id, translation, success)` — recent activity deque(maxlen=5)
- `set_stage(stage)` — current operation label
- `set_completed()` — final state
- `accept()` — dismiss the modal (required after set_completed)

**Emits:**
- `cancel_requested`, `pause_requested`, `resume_requested`

---

## 9. Migration Sequence

```
001–019: various features
020: pronunciation_entry
021: audio_usage_tracking
022: pronunciation_layer_v2
023: documents_metadata
024: sentence_pronunciation  ← latest applied
025: [RESERVED for Audio Player v2]
```

---

## 10. Design Decisions

### Persistence: SQLite (preferred)
DB tables for Queue/Playlist/History — crash-safe, migrable, testable.
QSettings for UI state only (column widths, visibility, speed, repeat mode).

### Queue: Non-destructive cursor
Replace `deque.popleft()` with `List[AudioTrack]` + `_current_index: int`.
Items stay in queue after playing; cursor advances.
Back-compat: all existing API (`play_paths`, `clear_queue`, `next_track`, `queue_snapshot`) preserved.

### Playback Rate: QMediaPlayer.setPlaybackRate()
Qt6 `QMediaPlayer` supports `setPlaybackRate(float)` natively.
Add `set_rate(rate)` to `AudioBackendBase` + `QtMultimediaBackend`.
Persist in QSettings `audio/playback/rate`.
Fallback: if backend unavailable, rate setting is a no-op.

### Source References
`AudioQueueItem` stores `(kind, source_id, project_id)` as the source reference
plus `snapshot_*` fields for display without DB round-trips.
`resolve_source_link()` maps `(kind, source_id)` → `{view_name, row_id}` for "Go to source".
