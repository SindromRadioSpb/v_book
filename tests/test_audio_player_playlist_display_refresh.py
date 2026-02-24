from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication
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


def test_playlist_display_refresh_updates_contexts_and_paths(panel, tmp_path):
    panel._playlist_entries_model.load_rows(
        [
            {
                "entry_id": 1,
                "position": 0,
                "kind": "sentence",
                "source_id": 12,
                "project_id": 7,
                "snapshot_hebrew": "שלום עולם",
                "snapshot_source_label": "before",
                "audio_status": "missing",
            }
        ]
    )

    def _refresh_sentence(_session, proxies):
        proxies[0].context["snapshot_niqqud"] = "שָׁלוֹם עוֹלָם"
        proxies[0].context["snapshot_translation"] = "hello world"
        proxies[0].context["snapshot_source_label"] = "doc_a.txt"
        proxies[0].context["snapshot_project_name"] = "Project A"
        proxies[0].context["snapshot_document_name"] = "doc_a.txt"
        return 1

    panel._refresh_sentence_display = _refresh_sentence
    panel._refresh_lemma_display = lambda _s, _p: 0
    panel._refresh_term_display = lambda _s, _p: 0

    ready_file = tmp_path / "ready.wav"
    ready_file.write_bytes(b"RIFF")
    panel._resolve_playlist_row_paths = lambda rows: (
        [ready_file],
        ["שלום עולם"],
        [{"kind": "sentence", "source_id": 12, "project_id": 7}],
        rows,
    )

    panel._refresh_playlist_display_contexts()
    payload = panel._playlist_entries_model.row_payload(0)
    assert payload is not None
    assert payload["snapshot_niqqud"] == "שָׁלוֹם עוֹלָם"
    assert payload["snapshot_translation"] == "hello world"
    assert payload["snapshot_source_label"] == "doc_a.txt"
    assert payload["snapshot_project_name"] == "Project A"
    assert payload["snapshot_document_name"] == "doc_a.txt"
    assert payload["audio_status"] == "ready"
    assert payload["resolved_path"] == str(ready_file)


def test_playlist_display_refresh_nonfatal_on_error(panel, caplog):
    panel._playlist_entries_model.load_rows(
        [
            {
                "entry_id": 2,
                "position": 0,
                "kind": "lemma",
                "source_id": 99,
                "project_id": 1,
                "snapshot_hebrew": "מילה",
                "audio_status": "missing",
            }
        ]
    )
    panel._refresh_sentence_display = lambda _s, _p: 0
    panel._refresh_lemma_display = lambda _s, _p: (_ for _ in ()).throw(RuntimeError("resolver failure"))
    panel._refresh_term_display = lambda _s, _p: 0

    with caplog.at_level(logging.WARNING):
        panel._refresh_playlist_display_contexts()

    assert any("Playlist display refresh failed" in rec.message for rec in caplog.records)
    payload = panel._playlist_entries_model.row_payload(0)
    assert payload is not None
    assert payload["snapshot_hebrew"] == "מילה"
