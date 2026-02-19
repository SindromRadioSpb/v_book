"""Internal audio player service (QtMultimedia queue + cadence engine)."""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List, Optional, Sequence

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
    """Singleton queue player service with cadence controls."""

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
        self._queue: Deque[AudioTrack] = deque()
        self._current: Optional[AudioTrack] = None
        self._backend = backend
        if self._backend is None:
            self._backend = self._build_default_backend()
        self._playback_state = "idle"

        self._pre_timer = QTimer(self)
        self._pre_timer.setSingleShot(True)
        self._pre_timer.timeout.connect(self._on_pre_roll_done)
        self._gap_timer = QTimer(self)
        self._gap_timer.setSingleShot(True)
        self._gap_timer.timeout.connect(self._on_gap_done)
        self._post_timer = QTimer(self)
        self._post_timer.setSingleShot(True)
        self._post_timer.timeout.connect(self._on_post_roll_done)

        self.pre_roll_ms = 200
        self.gap_ms = 550
        self.post_roll_ms = 300
        self.play_mode = "interrupt"
        self.reload_from_settings()

        if self._backend is not None:
            self._backend.finished.connect(self._on_backend_finished)
            self._backend.error.connect(self._on_backend_error)
            self._backend.state_changed.connect(self._on_backend_state_changed)

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

    def set_cadence(self, *, pre_roll_ms: int, gap_ms: int, post_roll_ms: int) -> None:
        self.pre_roll_ms = _clamp_ms(pre_roll_ms, self.pre_roll_ms)
        self.gap_ms = _clamp_ms(gap_ms, self.gap_ms)
        self.post_roll_ms = _clamp_ms(post_roll_ms, self.post_roll_ms)

    def set_play_mode(self, play_mode: str) -> None:
        self.play_mode = _normalize_play_mode(play_mode)

    def queue_snapshot(self) -> List[Dict[str, Any]]:
        return [track.to_payload() for track in self._queue]

    def remove_queue_index(self, index: int) -> bool:
        if index < 0 or index >= len(self._queue):
            return False
        # Deque remove by index with minimal overhead for small queues.
        items = list(self._queue)
        items.pop(index)
        self._queue = deque(items)
        self._emit_queue_changed()
        return True

    def clear_queue(self) -> None:
        self._queue.clear()
        self._emit_queue_changed()

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
            context = {}
            if contexts is not None and idx < len(contexts):
                context = dict(contexts[idx] or {})
            items.append(
                AudioTrack(
                    path=path_obj,
                    label=label or path_obj.stem,
                    context=context,
                )
            )
        if not items:
            return 0

        mode = _normalize_play_mode(play_mode or self.play_mode)
        if mode == "interrupt":
            self.stop(clear_queue=True)

        self._queue.extend(items)
        self._emit_queue_changed()
        if self._current is None and not self._timers_active():
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
        self._backend.resume()
        self._set_state("playing")

    def toggle_pause(self) -> None:
        if self._playback_state == "paused":
            self.resume()
        elif self._playback_state == "playing":
            self.pause()

    def stop(self, *, clear_queue: bool = True) -> None:
        self._pre_timer.stop()
        self._gap_timer.stop()
        self._post_timer.stop()
        if self._backend is not None:
            try:
                self._backend.stop()
            except Exception:
                pass
        self._current = None
        if clear_queue:
            self._queue.clear()
        self._emit_queue_changed()
        self._emit_now_playing(None)
        self._set_state("idle")

    def next_track(self) -> None:
        if self._backend is not None:
            try:
                self._backend.stop()
            except Exception:
                pass
        self._pre_timer.stop()
        self._post_timer.stop()
        self._gap_timer.stop()
        self._current = None
        self._emit_now_playing(None)
        self._start_next_track()

    def _timers_active(self) -> bool:
        return self._pre_timer.isActive() or self._post_timer.isActive() or self._gap_timer.isActive()

    def _start_next_track(self) -> None:
        if self._current is not None:
            return
        if not self._queue:
            self._set_state("idle")
            self._emit_now_playing(None)
            return

        self._current = self._queue.popleft()
        self._emit_queue_changed()
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
        self._current = None
        self._emit_now_playing(None)

        if self._queue:
            if self.gap_ms > 0:
                self._set_state("gap")
                self._gap_timer.start(self.gap_ms)
            else:
                self._start_next_track()
            return

        self._set_state("idle")

    def _on_gap_done(self) -> None:
        self._start_next_track()

    def _on_backend_error(self, message: str) -> None:
        payload = self._current.to_payload() if self._current else {}
        self.playback_error.emit(message or "Playback error", payload)
        self._current = None
        self._emit_now_playing(None)
        if self._queue:
            self._start_next_track()
        else:
            self._set_state("idle")

    def _on_backend_state_changed(self, state: str) -> None:
        # Keep explicit service states (pre/gap/post) intact.
        if self._playback_state in {"pre_roll", "post_roll", "gap"}:
            return
        if state in {"playing", "paused", "stopped"}:
            mapped = "idle" if state == "stopped" and self._current is None and not self._queue else state
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

