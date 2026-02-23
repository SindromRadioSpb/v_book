"""Tests for internal audio queue/cadence engine."""

from __future__ import annotations

from pathlib import Path

from app.services.audio_player_service import AudioBackendBase, AudioPlayerService


class _SettingsStub:
    def __init__(self, data=None):
        self._data = dict(data or {})

    def get_int(self, key: str, default: int = 0) -> int:
        return int(self._data.get(key, default))

    def get_string(self, key: str, default: str = "") -> str:
        return str(self._data.get(key, default))


class _FakeBackend(AudioBackendBase):
    def __init__(self):
        super().__init__()
        self.played_paths: list[Path] = []
        self.stopped = False

    def play(self, path: Path) -> bool:
        self.played_paths.append(Path(path))
        self.state_changed.emit("playing")
        return True

    def stop(self) -> None:
        self.stopped = True
        self.state_changed.emit("stopped")

    def pause(self) -> None:
        self.state_changed.emit("paused")

    def resume(self) -> None:
        self.state_changed.emit("playing")


def _touch_audio(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"RIFF")
    return path


def test_enqueue_mode_plays_items_in_order(tmp_path):
    backend = _FakeBackend()
    settings = _SettingsStub(
        {
            "audio/playback/pre_roll_ms": 0,
            "audio/playback/gap_ms": 0,
            "audio/playback/post_roll_ms": 0,
            "audio/playback/play_mode": "interrupt",
        }
    )
    service = AudioPlayerService(settings=settings, backend=backend)

    started_labels: list[str] = []
    service.track_started.connect(
        lambda payload: started_labels.append(str((payload or {}).get("label", "")))
    )

    p1 = _touch_audio(tmp_path / "one.wav")
    p2 = _touch_audio(tmp_path / "two.wav")
    p3 = _touch_audio(tmp_path / "three.wav")

    assert service.play_paths([p1], labels=["one"], play_mode="interrupt") == 1
    assert service.play_paths([p2, p3], labels=["two", "three"], play_mode="enqueue") == 2
    assert started_labels == ["one"]
    # v2: non-destructive — all 3 items stay in queue (p1 is current at index 0)
    assert len(service.queue_snapshot()) == 3

    backend.finished.emit()
    assert started_labels == ["one", "two"]
    backend.finished.emit()
    assert started_labels == ["one", "two", "three"]

    service.stop(clear_queue=True)


def test_interrupt_mode_clears_queue_and_starts_new_track(tmp_path):
    backend = _FakeBackend()
    settings = _SettingsStub(
        {
            "audio/playback/pre_roll_ms": 0,
            "audio/playback/gap_ms": 0,
            "audio/playback/post_roll_ms": 0,
            "audio/playback/play_mode": "enqueue",
        }
    )
    service = AudioPlayerService(settings=settings, backend=backend)

    p1 = _touch_audio(tmp_path / "a.wav")
    p2 = _touch_audio(tmp_path / "b.wav")
    p3 = _touch_audio(tmp_path / "c.wav")

    service.play_paths([p1, p2], labels=["a", "b"], play_mode="enqueue")
    # v2: non-destructive — both items stay in queue (p1 is current at index 0)
    assert len(service.queue_snapshot()) == 2

    service.play_paths([p3], labels=["c"], play_mode="interrupt")
    assert backend.stopped is True
    assert backend.played_paths[-1] == p3
    # After interrupt, queue is replaced with just p3 (p3 is current at index 0)
    assert len(service.queue_snapshot()) == 1

    service.stop(clear_queue=True)
