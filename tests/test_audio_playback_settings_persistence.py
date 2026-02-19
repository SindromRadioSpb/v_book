"""Tests for playback cadence/mode settings binding."""

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

    def set_value(self, key: str, value):
        self._data[key] = value


class _FakeBackend(AudioBackendBase):
    def play(self, path: Path) -> bool:
        self.state_changed.emit("playing")
        return True

    def stop(self) -> None:
        self.state_changed.emit("stopped")

    def pause(self) -> None:
        self.state_changed.emit("paused")

    def resume(self) -> None:
        self.state_changed.emit("playing")


def test_player_loads_and_reloads_playback_settings():
    settings = _SettingsStub(
        {
            "audio/playback/pre_roll_ms": 111,
            "audio/playback/gap_ms": 222,
            "audio/playback/post_roll_ms": 333,
            "audio/playback/play_mode": "enqueue",
        }
    )
    service = AudioPlayerService(settings=settings, backend=_FakeBackend())
    assert service.pre_roll_ms == 111
    assert service.gap_ms == 222
    assert service.post_roll_ms == 333
    assert service.play_mode == "enqueue"

    settings.set_value("audio/playback/pre_roll_ms", 444)
    settings.set_value("audio/playback/gap_ms", 555)
    settings.set_value("audio/playback/post_roll_ms", 666)
    settings.set_value("audio/playback/play_mode", "interrupt")

    service.reload_from_settings()
    assert service.pre_roll_ms == 444
    assert service.gap_ms == 555
    assert service.post_roll_ms == 666
    assert service.play_mode == "interrupt"

