from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication, QMessageBox
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.infra.sa_models import Base
from app.services.audio_player_service import AudioBackendBase, AudioPlayerService
from app.services.audio_queue_service import AudioItemSpec, AudioQueueService
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
        self._session_maker = sessionmaker(bind=self.engine)

    def get_session(self):
        return Session(self.engine)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def panel(qtbot, monkeypatch):
    settings = _SettingsStub()
    player = AudioPlayerService(settings=settings, backend=_FakeBackend())
    db = _DBStub()
    monkeypatch.setattr("app.services.db_service.DBService.get_instance", lambda: db)
    widget = AudioPlayerPanel(player=player, db=db)
    qtbot.addWidget(widget)
    widget.show()
    yield widget, player, db
    player.stop(clear_queue=True)


def _seed_queue_row(player: AudioPlayerService, audio_file: Path) -> None:
    player.play_paths(
        [audio_file],
        labels=["בית ספר גדול"],
        play_mode="interrupt",
        contexts=[
            {
                "kind": "term",
                "source_id": 31890,
                "project_id": 11,
                "snapshot_hebrew": "בית ספר גדול",
                "snapshot_niqqud": "בֵּית סֵפֶר גָּדוֹל",
                "snapshot_translation": "big school",
                "snapshot_source_label": "Project 11",
                "audio_status": "ready",
            }
        ],
    )
    player.stop(clear_queue=False)


def test_playlists_create_add_queue_selected_and_load(panel, monkeypatch, tmp_path):
    widget, player, db = panel

    audio_file = tmp_path / "sample.wav"
    audio_file.write_bytes(b"RIFF")
    _seed_queue_row(player, audio_file)

    monkeypatch.setattr("app.ui.widgets.audio_player_panel.QInputDialog.getText", lambda *_a, **_k: ("Lesson A", True))
    monkeypatch.setattr("app.ui.widgets.audio_player_panel.QInputDialog.getItem", lambda *_a, **_k: ("Append", True))
    monkeypatch.setattr("app.ui.widgets.audio_player_panel.QMessageBox.information", lambda *_a, **_k: QMessageBox.StandardButton.Ok)

    widget._on_new_playlist_clicked()
    assert widget.playlists_list.count() == 1
    assert "Lesson A" in widget.playlists_list.item(0).text()

    widget.playlists_list.setCurrentRow(0)
    widget.queue_table.selectRow(0)
    widget._on_add_queue_selected_to_playlist_clicked()

    assert widget._playlist_entries_model.entry_count() == 1

    widget._on_load_playlist_to_queue_clicked()
    assert widget._queue_model.rowCount() >= 1

    # DB queue row should exist after load.
    with db.get_session() as session:
        assert len(AudioQueueService().get_queue(session)) >= 1


def test_playlists_rename_and_delete(panel, monkeypatch):
    widget, _player, db = panel

    with db.get_session() as session:
        playlist_id = AudioQueueService().create_playlist(session, "Old Name")
        session.commit()

    widget._refresh_playlists(select_playlist_id=playlist_id)
    assert widget.playlists_list.count() >= 1

    monkeypatch.setattr("app.ui.widgets.audio_player_panel.QInputDialog.getText", lambda *_a, **_k: ("Renamed", True))
    widget._on_rename_playlist_clicked()
    assert "Renamed" in widget.playlists_list.currentItem().text()

    monkeypatch.setattr(
        "app.ui.widgets.audio_player_panel.QMessageBox.question",
        lambda *_a, **_k: QMessageBox.StandardButton.Yes,
    )
    widget._on_delete_playlist_clicked()
    assert all("Renamed" not in widget.playlists_list.item(i).text() for i in range(widget.playlists_list.count()))


def test_playlists_reorder_and_remove_entries(panel):
    widget, _player, db = panel

    with db.get_session() as session:
        svc = AudioQueueService()
        playlist_id = svc.create_playlist(session, "Reorder Me")
        svc.add_to_playlist(
            session,
            playlist_id,
            [
                AudioItemSpec(kind="term", source_id=1, snapshot_hebrew="one"),
                AudioItemSpec(kind="term", source_id=2, snapshot_hebrew="two"),
                AudioItemSpec(kind="term", source_id=3, snapshot_hebrew="three"),
            ],
        )
        session.commit()

    widget._refresh_playlists(select_playlist_id=playlist_id)
    assert widget._playlist_entries_model.entry_count() == 3

    widget.playlist_entries_table.selectRow(0)
    first_id_before = widget._playlist_entries_model.entry_id_at(0)
    second_id_before = widget._playlist_entries_model.entry_id_at(1)
    widget._on_move_playlist_entry(1)
    assert widget._playlist_entries_model.entry_id_at(0) == second_id_before
    assert widget._playlist_entries_model.entry_id_at(1) == first_id_before

    widget.playlist_entries_table.selectRow(1)
    widget._on_remove_playlist_entries_clicked()
    assert widget._playlist_entries_model.entry_count() == 2
