from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PyQt6.QtCore import QModelIndex
from PyQt6.QtWidgets import QApplication

from app.services.audio_player_service import AudioBackendBase, AudioPlayerService
from app.ui.widgets.audio_player_panel import _COL_STATUS, AudioPlayerPanel


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


@pytest.fixture
def panel_with_one_track(qtbot, tmp_path):
    settings = _SettingsStub()
    player = AudioPlayerService(settings=settings, backend=_FakeBackend())
    panel = AudioPlayerPanel(player=player)
    qtbot.addWidget(panel)

    audio_file = tmp_path / "sample.wav"
    audio_file.write_bytes(b"RIFF")
    player.play_paths(
        [audio_file],
        labels=["row"],
        play_mode="interrupt",
        contexts=[{"kind": "lemma", "source_id": 1, "project_id": 7, "snapshot_hebrew": "שלום"}],
    )
    player.stop(clear_queue=False)
    return panel, player


def test_clicking_missing_status_cell_shows_user_message(panel_with_one_track, monkeypatch):
    panel, player = panel_with_one_track
    player._tracks[0].path = Path("")  # noqa: SLF001
    player._tracks[0].context["audio_status"] = "missing"  # noqa: SLF001
    player._tracks[0].context["is_stale"] = False  # noqa: SLF001

    messages: list[str] = []
    starts = {"count": 0}
    monkeypatch.setattr(
        panel, "_show_status_message", lambda msg, timeout_ms=4500: messages.append(str(msg))
    )
    monkeypatch.setattr(
        player, "_start_next_track", lambda: starts.__setitem__("count", starts["count"] + 1)
    )

    idx: QModelIndex = panel._queue_model.index(0, _COL_STATUS)  # noqa: SLF001
    panel._on_queue_table_clicked(idx)

    assert messages
    assert "audio" in messages[0].lower()
    assert starts["count"] == 0


def test_play_stale_row_shows_user_message_and_does_not_play(panel_with_one_track, monkeypatch):
    panel, player = panel_with_one_track
    player._tracks[0].path = Path("")  # noqa: SLF001
    player._tracks[0].context["audio_status"] = "stale"  # noqa: SLF001
    player._tracks[0].context["is_stale"] = True  # noqa: SLF001

    messages: list[str] = []
    starts = {"count": 0}
    monkeypatch.setattr(
        panel, "_refresh_audio_paths_for_rows", lambda rows, clear_stale_if_ready=True: None
    )
    monkeypatch.setattr(
        panel, "_show_status_message", lambda msg, timeout_ms=4500: messages.append(str(msg))
    )
    monkeypatch.setattr(
        player, "_start_next_track", lambda: starts.__setitem__("count", starts["count"] + 1)
    )

    idx: QModelIndex = panel._queue_model.index(0, _COL_STATUS)  # noqa: SLF001
    panel._on_queue_play_cell_clicked(idx)

    assert messages
    assert "stale" in messages[0].lower()
    assert starts["count"] == 0
