"""Internal audio player service (QtMultimedia queue + cadence engine).

v2 changes (task 25):
- Non-destructive queue: items stay in _tracks after playing; _current_index
  cursor advances instead of removing items.
- Playback rate: QtMultimediaBackend.set_rate() → QMediaPlayer.setPlaybackRate().
- Repeat modes: "none" | "one" | "all".
- Auto-pause after each item.
- previous_track() support.
All existing public API is preserved (back-compat).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from PyQt6.QtCore import QCoreApplication, QObject, QTimer, QUrl, pyqtSignal

from app.infra.settings import SettingsService

logger = logging.getLogger(__name__)

try:
    from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer

    QT_MULTIMEDIA_AVAILABLE = True
except Exception:
    QAudioOutput = None  # type: ignore[assignment]
    QMediaPlayer = None  # type: ignore[assignment]
    QT_MULTIMEDIA_AVAILABLE = False


def _normalize_play_mode(raw: str) -> str:
    value = (raw or "").strip().lower()
    return "enqueue" if value == "enqueue" else "interrupt"


def _clamp_ms(value: int, default: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        return default
    return max(0, min(10000, parsed))


def _clamp_rate(value: float) -> float:
    try:
        f = float(value)
    except Exception:
        return 1.0
    return max(0.25, min(4.0, round(f, 4)))


@dataclass
class AudioTrack:
    """Queue item metadata for internal playback."""

    path: Path
    label: str = ""
    context: Dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "path": str(self.path),
            "label": self.label,
        }
        if self.context:
            payload["context"] = dict(self.context)
        return payload


class AudioBackendBase(QObject):
    """Backend contract for player engine."""

    finished = pyqtSignal()
    error = pyqtSignal(str)
    state_changed = pyqtSignal(str)

    def play(self, path: Path) -> bool:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def pause(self) -> None:
        raise NotImplementedError

    def resume(self) -> None:
        raise NotImplementedError

    def set_rate(self, rate: float) -> None:
        """Set playback rate (1.0 = normal speed).  No-op if unsupported."""

    def get_rate(self) -> float:
        """Return current playback rate."""
        return 1.0


class QtMultimediaBackend(AudioBackendBase):
    """QtMultimedia playback backend."""

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        if not QT_MULTIMEDIA_AVAILABLE:
            raise RuntimeError("QtMultimedia is not available")

        self._audio_output = QAudioOutput(self)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._audio_output)
        self._player.mediaStatusChanged.connect(self._on_media_status_changed)
        self._player.errorOccurred.connect(self._on_error)
        self._player.playbackStateChanged.connect(self._on_state_changed)

    def play(self, path: Path) -> bool:
        # Path("") serialises to "." — reject empty/current-dir sentinel values
        if not str(path) or str(path) == ".":
            self.error.emit("No audio file path provided (unresolved track)")
            return False
        if not path.exists():
            self.error.emit(f"Audio file does not exist: {path}")
            return False
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        self._player.play()
        return True

    def stop(self) -> None:
        self._player.stop()

    def pause(self) -> None:
        self._player.pause()

    def resume(self) -> None:
        self._player.play()

    def set_rate(self, rate: float) -> None:
        self._player.setPlaybackRate(_clamp_rate(rate))

    def get_rate(self) -> float:
        try:
            return float(self._player.playbackRate())
        except Exception:
            return 1.0

    def _on_media_status_changed(self, status) -> None:
        # EndOfMedia constant can differ across Qt wrappers, compare by name fallback.
        try:
            name = status.name
        except Exception:
            name = str(status)
        if name.endswith("EndOfMedia"):
            self.finished.emit()

    def _on_error(self, *_args) -> None:
        message = ""
        try:
            message = self._player.errorString()
        except Exception:
            message = "Unknown playback error"
        self.error.emit(message or "Unknown playback error")

    def _on_state_changed(self, state) -> None:
        try:
            name = state.name
        except Exception:
            name = str(state)
        normalized = "stopped"
        if name.endswith("PlayingState"):
            normalized = "playing"
        elif name.endswith("PausedState"):
            normalized = "paused"
        self.state_changed.emit(normalized)


class AudioPlayerService(QObject):
    """Singleton queue player service with cadence controls.

    v2: non-destructive queue (items stay after playing), on-the-fly playback
    rate, repeat modes (none/one/all), and auto-pause after each item.
    """

    _instance: Optional["AudioPlayerService"] = None

    queue_changed = pyqtSignal(list)
    now_playing_changed = pyqtSignal(object)
    playback_state_changed = pyqtSignal(str)
    track_started = pyqtSignal(object)
    track_finished = pyqtSignal(object)
    playback_error = pyqtSignal(str, object)

    def __init__(
        self,
        *,
        settings: Optional[SettingsService] = None,
        backend: Optional[AudioBackendBase] = None,
    ):
        super().__init__()
        self.settings = settings or SettingsService.get_instance()

        # Non-destructive queue: items are never popped on play.
        self._tracks: List[AudioTrack] = []
        # Index of the track that is currently (or was last) started.
        # -1 = nothing has been started yet.
        self._current_index: int = -1
        # Reference to the track physically held by the backend right now.
        self._current: Optional[AudioTrack] = None

        self._backend = backend
        if self._backend is None:
            self._backend = self._build_default_backend()
        self._playback_state = "idle"

        # Cadence timers
        self._pre_timer = QTimer(self)
        self._pre_timer.setSingleShot(True)
        self._pre_timer.timeout.connect(self._on_pre_roll_done)
        self._gap_timer = QTimer(self)
        self._gap_timer.setSingleShot(True)
        self._gap_timer.timeout.connect(self._on_gap_done)
        self._post_timer = QTimer(self)
        self._post_timer.setSingleShot(True)
        self._post_timer.timeout.connect(self._on_post_roll_done)

        # Cadence settings
        self.pre_roll_ms = 200
        self.gap_ms = 550
        self.post_roll_ms = 300
        self.play_mode = "interrupt"

        # v2: playback rate + repeat
        self._playback_rate: float = 1.0
        self._repeat_mode: str = "none"   # "none" | "one" | "all"
        self._repeat_count: int = 0       # 0 = infinite, N = play N times (mode="one")
        self._item_play_count: int = 0    # how many times the current item has finished
        self._auto_pause: bool = False    # pause after each item instead of auto-advancing

        self.reload_from_settings()

        if self._backend is not None:
            self._backend.finished.connect(self._on_backend_finished)
            self._backend.error.connect(self._on_backend_error)
            self._backend.state_changed.connect(self._on_backend_state_changed)

    # ── Singleton ─────────────────────────────────────────────────────────────

    @classmethod
    def get_instance(cls) -> "AudioPlayerService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance_for_tests(cls) -> None:
        if cls._instance is not None:
            try:
                cls._instance.stop(clear_queue=True)
            except Exception:
                pass
            try:
                cls._instance.deleteLater()
            except Exception:
                pass
        cls._instance = None

    @property
    def is_available(self) -> bool:
        return self._backend is not None

    @property
    def current_index(self) -> int:
        """Index of the currently-playing (or last-played) track, or -1."""
        return self._current_index

    # ── Settings ──────────────────────────────────────────────────────────────

    def _build_default_backend(self) -> Optional[AudioBackendBase]:
        if not QT_MULTIMEDIA_AVAILABLE:
            logger.warning("QtMultimedia is unavailable, internal playback disabled")
            return None
        if QCoreApplication.instance() is None:
            logger.warning("QCoreApplication is not initialized, internal playback disabled")
            return None
        try:
            return QtMultimediaBackend(self)
        except Exception as e:
            logger.warning("Failed to initialize QtMultimedia backend: %s", e)
            return None

    def reload_from_settings(self) -> None:
        self.pre_roll_ms = _clamp_ms(
            self.settings.get_int("audio/playback/pre_roll_ms", 200),
            200,
        )
        self.gap_ms = _clamp_ms(
            self.settings.get_int("audio/playback/gap_ms", 550),
            550,
        )
        self.post_roll_ms = _clamp_ms(
            self.settings.get_int("audio/playback/post_roll_ms", 300),
            300,
        )
        self.play_mode = _normalize_play_mode(
            self.settings.get_string("audio/playback/play_mode", "interrupt")
        )
        # Rate stored as string to avoid QSettings float precision issues
        try:
            rate = float(self.settings.get_string("audio/playback/rate", "1.0"))
        except (ValueError, TypeError):
            rate = 1.0
        self._playback_rate = _clamp_rate(rate)
        if self._backend is not None:
            self._backend.set_rate(self._playback_rate)

    def set_cadence(self, *, pre_roll_ms: int, gap_ms: int, post_roll_ms: int) -> None:
        self.pre_roll_ms = _clamp_ms(pre_roll_ms, self.pre_roll_ms)
        self.gap_ms = _clamp_ms(gap_ms, self.gap_ms)
        self.post_roll_ms = _clamp_ms(post_roll_ms, self.post_roll_ms)

    def set_play_mode(self, play_mode: str) -> None:
        self.play_mode = _normalize_play_mode(play_mode)

    # ── Playback rate ─────────────────────────────────────────────────────────

    def set_playback_rate(self, rate: float) -> None:
        """Set on-the-fly playback rate and persist to QSettings."""
        self._playback_rate = _clamp_rate(rate)
        if self._backend is not None:
            self._backend.set_rate(self._playback_rate)
        self.settings.set_value("audio/playback/rate", str(self._playback_rate))
        self.settings.sync()

    def get_playback_rate(self) -> float:
        return self._playback_rate

    # ── Repeat + auto-pause ───────────────────────────────────────────────────

    def set_repeat_mode(self, mode: str) -> None:
        """Set repeat mode: "none" | "one" | "all"."""
        if mode not in ("none", "one", "all"):
            mode = "none"
        self._repeat_mode = mode
        self._item_play_count = 0

    def set_repeat_count(self, count: int) -> None:
        """How many times to play each item before advancing (0 = infinite).
        Only effective when repeat_mode == "one".
        """
        self._repeat_count = max(0, int(count))

    def set_auto_pause(self, enabled: bool) -> None:
        """If True, pause after each item instead of auto-advancing."""
        self._auto_pause = bool(enabled)

    # ── Queue management ──────────────────────────────────────────────────────

    def queue_snapshot(self) -> List[Dict[str, Any]]:
        """Return ALL tracks (including already-played; cursor is in the UI)."""
        return [track.to_payload() for track in self._tracks]

    def remove_queue_index(self, index: int) -> bool:
        if index < 0 or index >= len(self._tracks):
            return False
        self._tracks.pop(index)
        if index < self._current_index:
            self._current_index -= 1
        elif index == self._current_index:
            # Currently-playing item removed — stop and back up one step
            self._stop_backend_only()
            self._current = None
            self._current_index = max(-1, self._current_index - 1)
        self._emit_queue_changed()
        return True

    def clear_queue(self) -> None:
        self._tracks.clear()
        self._current_index = -1
        self._current = None
        self._emit_queue_changed()

    def jump_to_index(self, index: int) -> None:
        """Stop current playback and immediately start the track at *index*."""
        if not self._tracks or not (0 <= index < len(self._tracks)):
            return
        if self._backend and self._current is not None:
            self._backend.stop()
        self._current = None
        self._item_play_count = 0
        self._current_index = index
        self._current = self._tracks[index]
        self._emit_queue_changed()
        self._begin_play_current()

    def enqueue_from_db(
        self,
        items: list,       # List[AudioQueueItemDTO] — avoids circular import
        *,
        mode: str = "append",   # "append" | "prepend" | "after_current"
        resolved_paths: Optional[Dict[int, Path]] = None,  # item_id → abs Path
    ) -> int:
        """Add AudioQueueItemDTO objects to the in-memory queue without requiring
        an audio file on disk.  Items with no ready audio appear as 'missing'
        in the Status column; playback skips them until audio is generated.

        ``mode`` mirrors play_paths() semantics:
          append        — add after the last existing track
          prepend       — insert before position 0 (shifts current_index)
          after_current — insert after current cursor position
        """
        tracks: List[AudioTrack] = []
        for item in items:
            label = (
                item.snapshot_hebrew
                or item.snapshot_source_label
                or f"{item.kind}:{item.source_id}"
            )
            ctx: Dict[str, Any] = {
                "snapshot_hebrew": item.snapshot_hebrew,
                "snapshot_niqqud": item.snapshot_niqqud,
                "snapshot_translation": item.snapshot_translation,
                "snapshot_source_label": item.snapshot_source_label,
                "source_id": item.source_id,
                "kind": item.kind,
                "project_id": item.project_id,
                "item_id": item.item_id,
                "audio_status": item.audio_status,
                "play_count": item.play_count,
            }
            resolved_path = (
                (resolved_paths or {}).get(item.item_id) or Path("")
            )
            tracks.append(AudioTrack(path=resolved_path, label=label, context=ctx))

        if not tracks:
            return 0

        if mode == "prepend":
            self._tracks = tracks + self._tracks
            if self._current_index >= 0:
                self._current_index += len(tracks)
        elif mode == "after_current":
            insert_at = max(0, self._current_index + 1)
            self._tracks = (
                self._tracks[:insert_at] + tracks + self._tracks[insert_at:]
            )
        else:  # append
            self._tracks.extend(tracks)

        self._emit_queue_changed()
        return len(tracks)

    # ── Playback control ──────────────────────────────────────────────────────

    def play_path(
        self,
        path: Path,
        *,
        label: str = "",
        play_mode: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> int:
        return self.play_paths(
            [path],
            labels=[label] if label else None,
            play_mode=play_mode,
            contexts=[context or {}],
        )

    def play_paths(
        self,
        paths: Sequence[Path],
        *,
        labels: Optional[Sequence[str]] = None,
        play_mode: Optional[str] = None,
        contexts: Optional[Sequence[Dict[str, Any]]] = None,
        start_immediately: bool = False,
    ) -> int:
        items: List[AudioTrack] = []
        for idx, path in enumerate(paths):
            if not path:
                continue
            path_obj = Path(path)
            if not path_obj.exists():
                continue
            label = ""
            if labels is not None and idx < len(labels):
                label = str(labels[idx] or "")
            ctx: Dict[str, Any] = {}
            if contexts is not None and idx < len(contexts):
                ctx = dict(contexts[idx] or {})
            # Keep queue Plays column deterministic for all entrypoints:
            # direct UI play actions (Dictionary/Terms/TM/UD) also start at 0.
            try:
                ctx["play_count"] = int(ctx.get("play_count", 0))
            except Exception:
                ctx["play_count"] = 0
            items.append(
                AudioTrack(
                    path=path_obj,
                    label=label or path_obj.stem,
                    context=ctx,
                )
            )
        if not items:
            return 0

        mode = _normalize_play_mode(play_mode or self.play_mode)
        if mode == "interrupt":
            self._stop_all_timers()
            self._stop_backend_only()
            self._tracks = list(items)
            self._current_index = -1
            self._current = None
            self._item_play_count = 0
            self._emit_queue_changed()
            self._emit_now_playing(None)
            self._set_state("idle")
            self._start_next_track()
        else:  # enqueue
            first_new_index = len(self._tracks)
            self._tracks.extend(items)
            self._emit_queue_changed()
            if start_immediately:
                # Premium UX for explicit row Play click: keep queue history,
                # append new item(s), but start playback from the clicked item now.
                self._stop_all_timers()
                self._stop_backend_only()
                self._current = None
                self._item_play_count = 0
                self._current_index = first_new_index - 1
                self._emit_now_playing(None)
                self._set_state("idle")
                self._start_next_track()
            elif self._current is None and not self._timers_active():
                self._start_next_track()

        return len(items)

    def pause(self) -> None:
        if self._backend is None:
            return
        self._backend.pause()
        self._set_state("paused")

    def resume(self) -> None:
        if self._backend is None:
            return
        if self._current is not None:
            self._backend.resume()
            self._set_state("playing")
        elif self._tracks:
            # No track loaded — pick up from where we paused (or start fresh)
            self._start_next_track()

    def toggle_pause(self) -> None:
        if self._playback_state == "paused":
            self.resume()
        elif self._playback_state == "playing":
            self.pause()

    def stop(self, *, clear_queue: bool = True) -> None:
        self._stop_all_timers()
        self._stop_backend_only()
        self._current = None
        if clear_queue:
            self._tracks.clear()
            self._current_index = -1
        self._item_play_count = 0
        self._emit_queue_changed()
        self._emit_now_playing(None)
        self._set_state("idle")

    def next_track(self) -> None:
        """Skip forward to the next track (ignores repeat-one for this skip)."""
        self._stop_all_timers()
        self._stop_backend_only()
        self._current = None
        self._item_play_count = 0
        self._emit_now_playing(None)
        # Bypass repeat-one so we actually advance
        saved_mode = self._repeat_mode
        self._repeat_mode = "none"
        self._start_next_track()
        self._repeat_mode = saved_mode

    def previous_track(self) -> None:
        """Go back to the previous track (or restart current if at index 0)."""
        self._stop_all_timers()
        self._stop_backend_only()
        self._current = None
        self._item_play_count = 0
        self._emit_now_playing(None)
        # Back the cursor so _start_next_track advances to the right position
        prev_index = max(0, self._current_index - 1)
        self._current_index = prev_index - 1
        saved_mode = self._repeat_mode
        self._repeat_mode = "none"
        self._start_next_track()
        self._repeat_mode = saved_mode

    # ── Internal playback engine ──────────────────────────────────────────────

    def _timers_active(self) -> bool:
        return (
            self._pre_timer.isActive()
            or self._post_timer.isActive()
            or self._gap_timer.isActive()
        )

    def _stop_all_timers(self) -> None:
        self._pre_timer.stop()
        self._gap_timer.stop()
        self._post_timer.stop()

    def _stop_backend_only(self) -> None:
        if self._backend is not None:
            try:
                self._backend.stop()
            except Exception:
                pass

    def _start_next_track(self) -> None:
        if self._current is not None:
            return

        # Repeat "one": replay current item if count not exhausted
        if self._repeat_mode == "one" and self._current_index >= 0:
            if self._repeat_count == 0 or self._item_play_count < self._repeat_count:
                self._current = self._tracks[self._current_index]
                self._begin_play_current()
                return
            else:
                # Count exhausted — fall through to advance
                self._item_play_count = 0

        next_idx = self._current_index + 1

        if next_idx >= len(self._tracks):
            if self._repeat_mode == "all" and self._tracks:
                next_idx = 0
                self._item_play_count = 0
            else:
                self._set_state("idle")
                self._emit_now_playing(None)
                return

        self._current_index = next_idx
        self._current = self._tracks[self._current_index]
        self._emit_queue_changed()  # so UI can highlight current row

        if self.pre_roll_ms > 0:
            self._set_state("pre_roll")
            self._pre_timer.start(self.pre_roll_ms)
            return
        self._begin_play_current()

    def _begin_play_current(self) -> None:
        track = self._current
        if track is None:
            return
        if self._backend is None:
            self.playback_error.emit("Internal audio backend is unavailable", track.to_payload())
            self._current = None
            self._start_next_track()
            return

        # Apply current rate before each play (in case backend was recreated)
        self._backend.set_rate(self._playback_rate)

        if not self._backend.play(track.path):
            self.playback_error.emit("Failed to start playback", track.to_payload())
            self._current = None
            self._start_next_track()
            return

        payload = track.to_payload()
        self.track_started.emit(payload)
        self._emit_now_playing(payload)
        self._set_state("playing")

    def _on_pre_roll_done(self) -> None:
        self._begin_play_current()

    def _on_backend_finished(self) -> None:
        if self._current is None:
            return
        if self.post_roll_ms > 0:
            self._set_state("post_roll")
            self._post_timer.start(self.post_roll_ms)
            return
        self._on_post_roll_done()

    def _on_post_roll_done(self) -> None:
        if self._current is None:
            return

        payload = self._current.to_payload()
        self.track_finished.emit(payload)

        # Tally plays for repeat-count logic
        self._item_play_count += 1

        # Update per-track play_count snapshot so the Plays column stays current
        if "play_count" in self._current.context:
            self._current.context["play_count"] += 1

        # Will we replay the same item?
        will_repeat_same = (
            self._repeat_mode == "one"
            and (self._repeat_count == 0 or self._item_play_count < self._repeat_count)
        )

        self._current = None
        self._emit_now_playing(None)
        self._emit_queue_changed()  # refresh Plays column regardless of next-track path

        if will_repeat_same:
            # Gap still applies between repeats of the same item
            if self.gap_ms > 0:
                self._set_state("gap")
                self._gap_timer.start(self.gap_ms)
            else:
                self._start_next_track()
            return

        # Auto-pause: user must press Next/Play to continue
        if self._auto_pause:
            self._set_state("paused")
            return

        # Determine if there is a next track (accounting for repeat-all)
        next_idx = self._current_index + 1
        has_next = next_idx < len(self._tracks) or (
            self._repeat_mode == "all" and self._tracks
        )

        if has_next:
            if self.gap_ms > 0:
                self._set_state("gap")
                self._gap_timer.start(self.gap_ms)
            else:
                self._start_next_track()
        else:
            self._item_play_count = 0
            self._set_state("idle")

    def _on_gap_done(self) -> None:
        self._start_next_track()

    def _on_backend_error(self, message: str) -> None:
        payload = self._current.to_payload() if self._current else {}
        self.playback_error.emit(message or "Playback error", payload)
        self._current = None
        self._emit_now_playing(None)
        next_idx = self._current_index + 1
        if next_idx < len(self._tracks):
            self._start_next_track()
        else:
            self._set_state("idle")

    def _on_backend_state_changed(self, state: str) -> None:
        # Keep explicit service states (pre/gap/post) intact.
        if self._playback_state in {"pre_roll", "post_roll", "gap"}:
            return
        if state in {"playing", "paused", "stopped"}:
            mapped = (
                "idle"
                if state == "stopped" and self._current is None and not self._tracks
                else state
            )
            self._set_state(mapped)

    def _emit_queue_changed(self) -> None:
        self.queue_changed.emit(self.queue_snapshot())

    def _emit_now_playing(self, payload: Optional[Dict[str, Any]]) -> None:
        self.now_playing_changed.emit(payload)

    def _set_state(self, state: str) -> None:
        if self._playback_state == state:
            return
        self._playback_state = state
        self.playback_state_changed.emit(state)
