# UI DoD Evidence — Audio Player v2

**Task:** 25 — Audio Player v2 (Premium)
**Date:** 2026-02-23
**Status:** PATCH-01–04 implemented; PATCH-05 pending

---

## Definition of Done Checklist

### Functional DoD

- [x] **Non-destructive queue** — items stay after playing; cursor advances
- [x] **Column-rich table UI** — Hebrew, Niqqud, Translation, Source, Status, Plays
- [x] **Column toggles** — gear menu, persisted to QSettings
- [x] **On-the-fly speed control** — 0.25×–4.0×, QMediaPlayer.setPlaybackRate()
- [x] **Speed persisted** — QSettings `audio/playback/rate`
- [x] **Repeat modes** — None / One / All + repeat count
- [x] **Auto-pause** — pause after each item
- [x] **Gap control** — 0–3000 ms live update
- [x] **Previous track** — J hotkey + ⏮ button
- [x] **Session History tab** — last 200 played items
- [x] **Hotkeys** — Space, J, K, +/=, -, R, Esc
- [x] **Context menu** — Play from here, Remove, Copy Hebrew/Niqqud/Translation
- [x] **Double-click to jump** — jumps cursor to that row
- [x] **DB migration 025** — audio_queue_item, audio_playlist, audio_playlist_entry, audio_history
- [x] **ORM models** — AudioQueueItem, AudioPlaylist, AudioPlaylistEntry, AudioHistory
- [x] **AudioQueueService** — Queue/Playlist/History CRUD
- [x] **Add All Filtered worker** — SQL chunked, V3 progress (PATCH-04)
- [x] **Source picker** — project/kind/mode picker dialog (PATCH-04)
- [ ] **Context actions** — Translate/Niqqudize/Regen/Edit Pronunciation/Edit Niqqud (PATCH-05)
- [ ] **Stale invalidation** — mark stale after pronunciation/niqqud edit (PATCH-05)
- [ ] **Playlist persistence** — DB-backed with full CRUD (PATCH-04)
- [ ] **DB History persistence** — across sessions (PATCH-04)
- [ ] **Go to Source** — navigate to originating view/row (PATCH-04)

### Safety DoD

- [x] No UI freeze — no long ops in UI thread
- [x] WAL-safe — all DB writes via short transactions
- [x] Back-compat — all existing entry points (play_paths, launch_audio_files) preserved
- [x] Import smoke passes — `python -c "import app; print('OK')"`

---

## Manual Smoke Test Scenarios

### Scenario 1: Toggle Audio Player opens dock

**Steps:**
1. Launch app
2. Press `Ctrl+Alt+L`
3. Verify dock appears at bottom
4. Press `Ctrl+Alt+L` again
5. Verify dock hides

**Expected:** Dock visibility toggles; layout not broken; state persists on restart.

---

### Scenario 2: Add rows → items stay after play

**Steps:**
1. Open Sentences view, select 3 sentences with audio
2. Right-click → Play Audio Selected
3. Audio Player opens (or was already open)
4. Play starts; first item plays
5. After track finishes (auto-advances to second)
6. Observe Queue tab

**Expected:**
- All 3 items remain in Queue table.
- First item shows ▶ marker while playing.
- After finishing, second item gets ▶ marker.
- No items disappear.

---

### Scenario 3: Speed change while playing

**Steps:**
1. Start playing a track
2. Change Speed spinbox from 1.0× to 0.7×
3. Listen to audio change speed in real time
4. Close and restart app
5. Open Audio Player

**Expected:**
- Speed changes immediately (no re-generation).
- After restart, Speed shows 0.7× (persisted).

---

### Scenario 4: Repeat One + auto-pause

**Steps:**
1. Add 3 items to queue
2. Set Repeat = One, Repeat Count = 2
3. Check Auto-pause
4. Play

**Expected:**
- First item plays twice, then audio pauses (auto-pause kicks in).
- Press Space to advance to next item.
- Next item plays twice, then pauses.
- Pattern continues.

---

### Scenario 5: Previous track (J key)

**Steps:**
1. Add 5 items, play through to item 3
2. Press J (previous track)

**Expected:**
- Item 2 starts playing.
- Queue table highlights item 2 with ▶.

---

### Scenario 6: Speed hotkeys

**Steps:**
1. Confirm speed is at 1.0×
2. Press + three times
3. Press - once

**Expected:**
- Speed becomes 1.3× after three `+`
- Speed becomes 1.2× after one `-`
- Speed spinbox updates in UI.

---

### Scenario 7: R key cycles repeat

**Steps:**
1. Press R (repeat mode = Off)
2. Observe Repeat combo → should show "One"
3. Press R again → "All"
4. Press R again → "Off"

**Expected:** Three R presses cycle Off → One → All → Off.

---

### Scenario 8: Column toggle

**Steps:**
1. Click ⚙ gear button
2. Uncheck "Niqqud" and "Translation"
3. Observe table

**Expected:**
- Niqqud and Translation columns hidden.
- Hebrew and Source columns still visible.
- State persisted on restart.

---

### Scenario 9: Context menu — Remove

**Steps:**
1. Add 5 items to queue
2. Right-click row 3 → Remove from Queue

**Expected:**
- Row 3 removed.
- 4 items remain.
- Positions repacked (no gaps).

---

### Scenario 10: History tab

**Steps:**
1. Play 3 tracks to completion
2. Click History tab

**Expected:**
- 3 entries shown, newest at top.
- Format: `[HH:MM:SS]  <track label>`.

---

## Hotkeys Reference Card

| Key | Action |
|-----|--------|
| Space | Play / Pause |
| J | Previous track |
| K | Next track |
| + or = | Speed +0.1× |
| - | Speed -0.1× |
| R | Cycle repeat: Off → One → All |
| Esc | Stop (keep queue) |

*All hotkeys are WidgetWithChildrenShortcut — active when Audio Player panel has focus.*

---

## Known Limitations (this iteration)

1. **Playlists tab** shows a placeholder — full DB-backed playlist CRUD requires PATCH-04.
2. **History tab** is session-only — DB persistence across restarts requires PATCH-04.
3. **Add All Filtered** not yet implemented — requires PATCH-04 worker.
4. **Context actions** (Translate/Edit Pronunciation/etc.) not yet wired — PATCH-05.
5. **Stale invalidation** not yet wired — PATCH-05.
6. **Go to Source** button is enabled/disabled but navigation not yet implemented — PATCH-04.
