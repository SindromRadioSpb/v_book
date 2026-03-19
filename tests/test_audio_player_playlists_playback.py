from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication, QMessageBox
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.infra.sa_models import Base
from app.services.audio_player_service import AudioBackendBase, AudioPlayerService
from app.ui.widgets.audio_player_panel import AudioPlayerPanel


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


class _DBStub:
    def __init__(self):
        self.engine = create_engine("sqlite:///:memory:", echo=False)
        Base.metadata.create_all(self.engine)

    def get_session(self):
        return Session(self.engine)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def panel(qtbot, monkeypatch):
    settings = _SettingsStub()
    monkeypatch.setattr("app.infra.settings.SettingsService.get_instance", lambda: settings)
    player = AudioPlayerService(settings=settings, backend=_FakeBackend())
    db = _DBStub()
    monkeypatch.setattr("app.services.db_service.DBService.get_instance", lambda: db)
    widget = AudioPlayerPanel(player=player, db=db)
    qtbot.addWidget(widget)
    widget.show()
    yield widget
    player.stop(clear_queue=True)


def test_playlist_play_selected_launches_audio(panel, monkeypatch, tmp_path):
    calls = {}
    audio_file = tmp_path / "ready.wav"
    audio_file.write_bytes(b"RIFF")

    # A playlist must be selected — action state requires has_playlist=True.
    panel._selected_playlist_id = 1

    panel._playlist_entries_model.load_rows(
        [
            {
                "entry_id": 1,
                "position": 0,
                "kind": "lemma",
                "source_id": 42,
                "project_id": 7,
                "snapshot_hebrew": "שלום",
                "snapshot_niqqud": "שָׁלוֹם",
                "snapshot_translation": "hello",
                "snapshot_source_label": "Dictionary",
                "audio_status": "ready",
            }
        ]
    )
    panel.playlist_entries_table.selectRow(0)

    monkeypatch.setattr(
        panel,
        "_resolve_playlist_row_paths",
        lambda rows: (
            [audio_file],
            ["שלום"],
            [{"kind": "lemma", "source_id": 42, "project_id": 7}],
            rows,
        ),
    )

    def _capture(paths, **kwargs):
        calls["paths"] = list(paths)
        calls["kwargs"] = kwargs
        return len(paths)

    monkeypatch.setattr(
        "app.services.audio_playback_service.AudioPlaybackService.launch_audio_files", _capture
    )
    panel._on_play_playlist_selected_clicked()

    assert calls["paths"] == [audio_file]
    assert calls["kwargs"]["play_mode"] == "enqueue"
    assert calls["kwargs"]["start_immediately"] is True


def test_playlist_play_selected_missing_shows_info(panel, monkeypatch):
    # A playlist must be selected — action state requires has_playlist=True.
    panel._selected_playlist_id = 1

    panel._playlist_entries_model.load_rows(
        [
            {
                "entry_id": 2,
                "position": 0,
                "kind": "term",
                "source_id": 99,
                "project_id": 3,
                "snapshot_hebrew": "בית",
                "audio_status": "missing",
            }
        ]
    )
    panel.playlist_entries_table.selectRow(0)

    # "missing" status → any_ready=False → action state disabled → _show_status_message
    # is called instead of launching audio. No QMessageBox.information in this path.
    shown = {"count": 0}

    def _status_msg(message, timeout_ms=4500):
        shown["count"] += 1

    monkeypatch.setattr(panel, "_show_status_message", _status_msg)
    monkeypatch.setattr(
        "app.services.audio_playback_service.AudioPlaybackService.launch_audio_files",
        lambda *_a, **_k: pytest.fail("launch_audio_files must not be called for missing paths"),
    )
    panel._on_play_playlist_selected_clicked()
    assert shown["count"] == 1


def test_resolve_playlist_row_paths_does_not_raise(panel):
    panel._playlist_entries_model.load_rows(
        [
            {
                "entry_id": 3,
                "position": 0,
                "kind": "lemma",
                "source_id": 101,
                "project_id": 5,
                "snapshot_hebrew": "שלום",
                "audio_status": "missing",
            }
        ]
    )
    paths, labels, contexts, rows = panel._resolve_playlist_row_paths([0])
    assert paths == []
    assert labels == []
    assert contexts == []
    assert rows == []
