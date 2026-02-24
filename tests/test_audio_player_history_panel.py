from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

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
            "audio_player/history_limit": 200,
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
    yield widget, db
    player.stop(clear_queue=True)


def _seed_history(db: _DBStub, *, kind: str, source_id: int, project_id: int, hebrew: str) -> None:
    with db.get_session() as session:
        svc = AudioQueueService()
        item_ids = svc.add_to_queue(
            session,
            [
                AudioItemSpec(
                    kind=kind,
                    source_id=source_id,
                    project_id=project_id,
                    snapshot_hebrew=hebrew,
                )
            ],
        )
        svc.mark_played(session, item_ids[0], rate_used=1.25)
        session.commit()


def test_history_tab_is_db_backed(panel):
    widget, db = panel
    _seed_history(db, kind="term", source_id=31890, project_id=11, hebrew="בית ספר גדול")

    with db.get_session() as session:
        AudioQueueService().clear_queue(session)
        session.commit()

    widget._refresh_history_entries()
    widget._refresh_history_display_contexts()

    assert widget._history_model.entry_count() == 1  # noqa: SLF001
    assert widget.tab_widget.tabText(2).startswith("History (1)")
    row = widget._history_model.row_payload(0)  # noqa: SLF001
    assert row is not None
    assert row["snapshot_hebrew"] == "בית ספר גדול"
    assert row["played_at"]


def test_go_to_source_uses_selected_playlist_row_when_playlist_tab_active(panel):
    widget, db = panel
    with db.get_session() as session:
        svc = AudioQueueService()
        playlist_id = svc.create_playlist(session, "Go Source Playlist")
        svc.add_to_playlist(
            session,
            playlist_id,
            [
                AudioItemSpec(
                    kind="lemma",
                    source_id=77,
                    project_id=5,
                    snapshot_hebrew="עקומה",
                )
            ],
        )
        session.commit()

    captured = []
    widget.go_to_source_requested.connect(captured.append)

    widget._refresh_playlists(select_playlist_id=playlist_id)
    widget.tab_widget.setCurrentIndex(1)
    widget.playlist_entries_table.selectRow(0)

    assert widget.goto_source_btn.isEnabled() is True
    widget.goto_source_btn.click()

    assert len(captured) == 1
    assert captured[0]["kind"] == "lemma"
    assert captured[0]["source_id"] == 77
    assert captured[0]["project_id"] == 5


def test_go_to_source_uses_selected_history_row_when_history_tab_active(panel):
    widget, db = panel
    _seed_history(db, kind="sentence", source_id=901, project_id=8, hebrew="בית הספר החדש")

    captured = []
    widget.go_to_source_requested.connect(captured.append)

    widget._refresh_history_entries()
    widget.tab_widget.setCurrentIndex(2)
    widget.history_table.selectRow(0)

    assert widget.goto_source_btn.isEnabled() is True
    widget.goto_source_btn.click()

    assert len(captured) >= 1
    assert captured[-1]["kind"] == "sentence"
    assert captured[-1]["source_id"] == 901
    assert captured[-1]["project_id"] == 8
