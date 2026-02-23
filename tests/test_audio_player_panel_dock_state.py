"""Tests for audio player panel + dock integration basics."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDockWidget, QMainWindow

from app.services.audio_player_service import AudioBackendBase, AudioPlayerService
from app.ui.widgets.audio_player_panel import AudioPlayerPanel


class _SettingsStub:
    def __init__(self):
        self._data = {
            "audio/playback/pre_roll_ms": 0,
            "audio/playback/gap_ms": 0,
            "audio/playback/post_roll_ms": 0,
            "audio/playback/play_mode": "enqueue",
        }

    def get_int(self, key: str, default: int = 0) -> int:
        return int(self._data.get(key, default))

    def get_string(self, key: str, default: str = "") -> str:
        return str(self._data.get(key, default))

    def get_bool(self, key: str, default: bool = False) -> bool:
        return bool(self._data.get(key, default))

    def get_json(self, key: str, default=None):
        return self._data.get(key, default)

    def set_value(self, key: str, value):
        self._data[key] = value

    def set_json(self, key: str, value):
        self._data[key] = value

    def sync(self):
        return None


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


def test_audio_player_panel_updates_queue_and_dock_visibility(qtbot, tmp_path):
    settings = _SettingsStub()
    player = AudioPlayerService(settings=settings, backend=_FakeBackend())

    main = QMainWindow()
    qtbot.addWidget(main)
    dock = QDockWidget("Audio Player", main)
    panel = AudioPlayerPanel(player=player, parent=dock)
    dock.setWidget(panel)
    main.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
    main.show()

    p1 = tmp_path / "p1.wav"
    p2 = tmp_path / "p2.wav"
    p1.write_bytes(b"RIFF")
    p2.write_bytes(b"RIFF")
    player.play_paths([p1, p2], labels=["one", "two"], play_mode="enqueue")

    # v2: non-destructive queue — both items stay; table model shows 2 rows
    assert panel._queue_model.rowCount() == 2
    assert "one" in panel.now_playing_label.text()

    dock.setVisible(False)
    assert dock.isVisible() is False
    dock.setVisible(True)
    assert dock.isVisible() is True

    player.stop(clear_queue=True)

