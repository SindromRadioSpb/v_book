"""Tests for shared add-to-playlist helper used by external views."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtWidgets import QDialog
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.infra.sa_models import Base
from app.services.audio_queue_service import AudioQueueService
from app.ui.audio_playlist_actions import add_selected_items_to_playlist_dialog


class _DBStub:
    def __init__(self):
        self.engine = create_engine("sqlite:///:memory:", echo=False)
        Base.metadata.create_all(self.engine)

    def get_session(self):
        return Session(self.engine)


class _Signal:
    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)

    def emit(self, value):
        for callback in self._callbacks:
            callback(value)


@dataclass
class _PanelStub:
    calls: list

    def refresh_playlists_view(self, *, select_playlist_id=None):
        self.calls.append(select_playlist_id)


class _WindowStub:
    def __init__(self, panel):
        self.audio_player_panel = panel


class _ParentStub:
    def __init__(self, panel):
        self._window = _WindowStub(panel)

    def window(self):
        return self._window


def test_add_selected_items_to_playlist_refreshes_audio_panel(monkeypatch):
    db = _DBStub()
    with db.get_session() as session:
        playlist_id = AudioQueueService().create_playlist(session, "Lesson A")
        session.commit()

    panel = _PanelStub(calls=[])
    parent = _ParentStub(panel)

    class _Dialog:
        def __init__(self, *args, **kwargs):
            self.playlist_created = _Signal()

        def exec(self):
            self.playlist_created.emit(playlist_id)
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
    monkeypatch.setattr("app.ui.audio_playlist_actions.QMessageBox.information", lambda *_a, **_k: None)
    monkeypatch.setattr("app.ui.audio_playlist_actions.QMessageBox.warning", lambda *_a, **_k: None)

    ok = add_selected_items_to_playlist_dialog(
        parent=parent,
        items=[
            {
                "kind": "sentence",
                "source_id": 42,
                "project_id": 7,
                "src_text": "בית ספר חדש",
                "pronunciation_text": "בֵּית סֵפֶר חָדָשׁ",
                "translation": "new school",
            }
        ],
        db_manager=db,
    )

    assert ok is True
    # At least one refresh from creation signal and one refresh after add commit.
    assert panel.calls
    assert playlist_id in panel.calls

    with db.get_session() as session:
        entries = AudioQueueService().get_playlist_entries(session, playlist_id)
    assert len(entries) == 1
    assert entries[0].source_id == 42
