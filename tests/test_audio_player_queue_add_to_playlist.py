from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.infra.sa_models import Base
from app.services.audio_player_service import AudioBackendBase, AudioPlayerService
from app.services.audio_queue_service import AudioQueueService
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
def setup_panel(qtbot, monkeypatch, tmp_path):
    settings = _SettingsStub()
    monkeypatch.setattr("app.infra.settings.SettingsService.get_instance", lambda: settings)
    player = AudioPlayerService(settings=settings, backend=_FakeBackend())
    db = _DBStub()
    monkeypatch.setattr("app.services.db_service.DBService.get_instance", lambda: db)

    panel = AudioPlayerPanel(player=player, db=db)
    qtbot.addWidget(panel)
    panel.show()

    # One queue row.
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")
    player.play_paths(
        [audio],
        labels=["מילה"],
        play_mode="interrupt",
        contexts=[
            {
                "kind": "lemma",
                "source_id": 55,
                "project_id": 9,
                "snapshot_hebrew": "מילה",
                "snapshot_niqqud": "מִילָה",
                "snapshot_translation": "word",
                "snapshot_source_label": "Dictionary",
                "audio_status": "ready",
            }
        ],
    )
    player.stop(clear_queue=False)

    with db.get_session() as session:
        playlist_id = AudioQueueService().create_playlist(session, "Lesson")
        session.commit()

    yield panel, db, playlist_id
    player.stop(clear_queue=True)


def test_queue_add_to_playlist_dedup(setup_panel, monkeypatch):
    panel, db, playlist_id = setup_panel
    panel.queue_table.selectRow(0)

    class _Dialog:
        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

        def selected_playlist_id(self):
            return playlist_id

        def selected_add_mode(self):
            return "append"

        def dedup_enabled(self):
            return True

        def selected_after_entry_id(self):
            return None

    monkeypatch.setattr("app.ui.widgets.audio_player_panel.AddQueueToPlaylistDialog", _Dialog)
    monkeypatch.setattr("app.ui.widgets.audio_player_panel.QMessageBox.information", lambda *_a, **_k: QMessageBox.StandardButton.Ok)

    panel._on_add_queue_selected_to_playlist_clicked()
    panel._on_add_queue_selected_to_playlist_clicked()

    with db.get_session() as session:
        entries = AudioQueueService().get_playlist_entries(session, playlist_id)
    assert len(entries) == 1
    assert entries[0].source_id == 55
