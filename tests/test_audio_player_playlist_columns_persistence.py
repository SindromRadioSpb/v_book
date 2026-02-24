from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

from app.services.audio_player_service import AudioBackendBase, AudioPlayerService
from app.ui.widgets.audio_player_panel import (
    AudioPlayerPanel,
    _COL_PROJECT,
    _COL_SOURCE_ID,
    _PL_COL_DOCUMENT,
    _PL_COL_SOURCE_ID,
)


class _SettingsStub:
    def __init__(self):
        self._data = {
            "audio/playback/pre_roll_ms": 0,
            "audio/playback/gap_ms": 0,
            "audio/playback/post_roll_ms": 0,
            "audio/playback/play_mode": "enqueue",
            "audio/playback/rate": "1.0",
        }

    def get_int(self, key: str, default: int = 0) -> int:
        return int(self._data.get(key, default))

    def get_string(self, key: str, default: str = "") -> str:
        return str(self._data.get(key, default))

    def get_bool(self, key: str, default: bool = False) -> bool:
        return bool(self._data.get(key, default))

    def get_json(self, key: str, default=None):
        return self._data.get(key, default)

    def get_bytes(self, key: str, default: bytes = b"") -> bytes:
        value = self._data.get(key, default)
        if isinstance(value, bytes):
            return value
        return default

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


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def _action_by_col(actions, col):
    for action in actions:
        if action.data() == col:
            return action
    raise AssertionError(f"Action for col {col} not found")


def test_queue_and_playlist_columns_visibility_persist(qtbot, monkeypatch):
    settings = _SettingsStub()
    monkeypatch.setattr("app.infra.settings.SettingsService.get_instance", lambda: settings)

    player1 = AudioPlayerService(settings=settings, backend=_FakeBackend())
    panel1 = AudioPlayerPanel(player=player1)
    qtbot.addWidget(panel1)
    panel1.show()

    # Queue: hide Project, show Source ID.
    _action_by_col(panel1._col_actions, _COL_PROJECT).setChecked(False)
    _action_by_col(panel1._col_actions, _COL_SOURCE_ID).setChecked(True)

    # Playlist: hide Document, show Source ID.
    _action_by_col(panel1._playlist_col_actions, _PL_COL_DOCUMENT).setChecked(False)
    _action_by_col(panel1._playlist_col_actions, _PL_COL_SOURCE_ID).setChecked(True)

    assert panel1.queue_table.isColumnHidden(_COL_PROJECT)
    assert not panel1.queue_table.isColumnHidden(_COL_SOURCE_ID)
    assert panel1.playlist_entries_table.isColumnHidden(_PL_COL_DOCUMENT)
    assert not panel1.playlist_entries_table.isColumnHidden(_PL_COL_SOURCE_ID)

    # New panel restores visibility from settings.
    player2 = AudioPlayerService(settings=settings, backend=_FakeBackend())
    panel2 = AudioPlayerPanel(player=player2)
    qtbot.addWidget(panel2)
    panel2.show()

    assert panel2.queue_table.isColumnHidden(_COL_PROJECT)
    assert not panel2.queue_table.isColumnHidden(_COL_SOURCE_ID)
    assert panel2.playlist_entries_table.isColumnHidden(_PL_COL_DOCUMENT)
    assert not panel2.playlist_entries_table.isColumnHidden(_PL_COL_SOURCE_ID)
