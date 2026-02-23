# Audio Player v2 — Usage Guide

**Task:** 25 — Audio Player v2 (Premium)
**Date:** 2026-02-23

---

## Overview

The Audio Player v2 transforms the minimal v1 list-player into a premium
learning tool for Hebrew audio review.  Key improvements:

| Feature | v1 | v2 |
|---------|----|----|
| Queue | Destructive (items removed on play) | **Non-destructive** (cursor advances, items stay) |
| Columns | Label only | Hebrew · Niqqud · Translation · Source · Status · Plays |
| Speed | None | **On-the-fly** 0.25×–4.0×, persisted |
| Repeat | None | **None / One / All** + repeat count |
| Auto-pause | None | ✓ after each item |
| Previous track | None | ✓ J hotkey |
| History | None | **Session history** in History tab |
| Playlists | None | DB-backed (PATCH-04+) |
| Column toggles | None | ✓ gear menu, persisted |

---

## Opening the Player

- **Menu:** View → Toggle Audio Player
- **Shortcut:** `Ctrl+Alt+L`
- **Dock:** Bottom (resizable; can be dragged to Right)

---

## Queue Semantics

### What "non-destructive" means

In v1, each track was **removed** from the queue the moment it started playing
(`deque.popleft()`). In v2:

- All tracks stay in `_tracks: List[AudioTrack]`.
- A `_current_index: int` cursor points to the track being played.
- After play, the cursor advances; **nothing is deleted**.
- You can use **Previous** (J) to replay already-heard items.
- The queue list always shows **all items** with the current one highlighted in green.

### Queue / Playlist / History (DB layer)

From PATCH-04 onward, the DB tables `audio_queue_item`, `audio_playlist`, and
`audio_history` store rich snapshots (Hebrew · Niqqud · Translation) and
survive app restarts.  The in-memory `_tracks` list remains the playback engine
(the DB layer acts as persistent metadata).

---

## Playback Controls

### Transport buttons

| Button | Hotkey | Action |
|--------|--------|--------|
| ⏮ | J | Previous track |
| ▶/⏸ | Space | Play / Pause |
| ⏭ | K | Next track |
| ⏹ | Esc | Stop (keep queue) |

### Speed control

- Range: **0.25×** to **4.0×**, step 0.1.
- Changed on-the-fly via `QMediaPlayer.setPlaybackRate()`.
- **Persisted** to QSettings `audio/playback/rate`.
- Hotkeys: `+` / `=` speed up; `-` speed down (each step = 0.1×).

### Repeat modes (R hotkey to cycle)

| Mode | Behaviour |
|------|-----------|
| **Off** | Queue plays once end-to-end, then stops. |
| **One** | Current item replays (infinite or N times per `repeat_count`). |
| **All** | Queue loops back to item 0 at the end. |

### Auto-pause

When checked, playback **pauses after each item** instead of auto-advancing.
Press Space or ⏭ to continue.

### Gap between items

Sets the silence between consecutive items (0–3 000 ms).  Updated live.

### Cadence presets

| Preset | Pre-roll | Gap | Post-roll |
|--------|----------|-----|-----------|
| Normal | 200 ms | 550 ms | 300 ms |
| Study  | 300 ms | 800 ms | 450 ms |
| Fast   | 100 ms | 250 ms | 120 ms |

---

## Column Visibility

Click the **⚙** gear button to toggle columns:
- Niqqud, Translation, Source, Status, Plays
- Column visibility is persisted to QSettings `audio_player/columns_visible`.

---

## Tabs

### Queue tab

Shows **all** items in the current queue.
- **▶** marker in the `#` column = currently playing.
- Green row = current track.
- Yellow/orange row = stale (source text changed since audio was cached).
- Double-click a row to jump to it.
- Right-click for context menu: Play from here · Remove · Copy Hebrew/Niqqud/Translation.

### Playlists tab

Named playlists persisted to the `audio_playlist` / `audio_playlist_entry` DB
tables (from PATCH-04).  Placeholder shown if DB session not available.

### History tab

Session listen history (last 200 entries, newest at top).  Entries persist
in the `audio_history` DB table between sessions (from PATCH-04).

---

## Adding Items to the Queue

Items are added by selecting rows in any view (Sentences, Dictionary, Terms,
User Dictionaries) and using **Play Audio Selected** from the context menu or
toolbar.

From PATCH-04 onward, **Add All Filtered (All pages)** will bulk-load the
entire current filtered view via a background SQL worker with a V3 progress
dialog (no UI freeze).

---

## Go to Source

The **Go to Source** button (enabled when a track with source metadata is
playing) navigates to the originating row in the correct view
(Sentences / Dictionary / Terms).

---

## Hotkeys Summary

| Key | Action |
|-----|--------|
| Space | Play / Pause |
| J | Previous track |
| K | Next track |
| + or = | Speed up 0.1× |
| - | Speed down 0.1× |
| R | Cycle repeat mode |
| Esc | Stop (keep queue) |

Hotkeys are **WidgetWithChildrenShortcut** — active when the Audio Player dock
has keyboard focus.

---

## Technical Notes

### Backend: QMediaPlayer.setPlaybackRate()

Runtime speed is implemented via `QtMultimediaBackend.set_rate()` which calls
`QMediaPlayer.setPlaybackRate(float)`.  This is available in Qt 6 and requires
no audio re-generation.  The `speed` column in `AudioAsset` records the speed
at which TTS was *generated* — that is separate from runtime rate.

### Non-destructive queue implementation

```
AudioPlayerService._tracks: List[AudioTrack]   # all items (never popped)
AudioPlayerService._current_index: int          # cursor (-1 = not started)
AudioPlayerService._current: Optional[AudioTrack]  # item held by backend now
```

### Repeat-one count

`set_repeat_count(N)` (N > 0): play current item N times before advancing.
`set_repeat_count(0)`: infinite repeat of current item.

### WAL / DB safety

`AudioQueueService` methods accept an open `Session`; the caller is responsible
for committing.  All writes use short transactions; no long locks.
