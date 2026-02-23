from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

from app.services.audio_player_service import AudioBackendBase, AudioPlayerService
from app.ui.widgets.audio_player_panel import AudioPlayerPanel


class _SettingsStub:
    def __init__(self):
        self._data = {
            "audio/playback/pre_roll_ms": 0,
            "audio/playback/gap_ms": 0,
            "audio/playback/post_roll_ms": 0,
            "audio/playback/play_mode": "enqueue",
            "audio/playback/rate": "1.25",
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


def _build_panel(tmp_path):
    settings = _SettingsStub()
    player = AudioPlayerService(settings=settings, backend=_FakeBackend())
    panel = AudioPlayerPanel(player=player)
    audio_file = tmp_path / "sample.wav"
    audio_file.write_bytes(b"RIFF")
    return panel, player, audio_file


def test_go_to_source_emits_current_track_context(qtbot, tmp_path):
    panel, player, audio_file = _build_panel(tmp_path)
    qtbot.addWidget(panel)
    captured = []
    panel.go_to_source_requested.connect(captured.append)

    player.play_paths(
        [audio_file],
        labels=["test"],
        play_mode="interrupt",
        contexts=[
            {
                "kind": "lemma",
                "source_id": 42,
                "project_id": 7,
                "item_id": 1,
            }
        ],
    )

    assert panel.goto_source_btn.isEnabled() is True
    panel.goto_source_btn.click()

    assert len(captured) == 1
    assert captured[0]["kind"] == "lemma"
    assert captured[0]["source_id"] == 42
    assert captured[0]["project_id"] == 7


def test_track_finished_marks_played_in_db(monkeypatch, qtbot, tmp_path):
    panel, player, audio_file = _build_panel(tmp_path)
    qtbot.addWidget(panel)
    player.play_paths(
        [audio_file],
        labels=["test"],
        play_mode="interrupt",
        contexts=[{"item_id": 99}],
    )

    calls = {"commits": 0}

    class _FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def commit(self):
            calls["commits"] += 1

    class _FakeDB:
        def get_session(self):
            return _FakeSession()

    def _fake_mark_played(self, session, item_id, rate_used=1.0):  # noqa: ARG001
        calls["item_id"] = item_id
        calls["rate_used"] = rate_used

    monkeypatch.setattr("app.services.db_service.DBService.get_instance", lambda: _FakeDB())
    monkeypatch.setattr("app.services.audio_queue_service.AudioQueueService.mark_played", _fake_mark_played)

    expected_rate = player.get_playback_rate()
    panel._on_track_finished({"label": "x", "context": {"item_id": 99}})

    assert calls["item_id"] == 99
    assert calls["commits"] == 1
    assert calls["rate_used"] == pytest.approx(expected_rate)
    assert panel.history_list.count() == 1
    assert player._tracks[0].context.get("last_played_at")  # noqa: SLF001


def test_track_finished_without_item_id_does_not_write_db(monkeypatch, qtbot, tmp_path):
    panel, _player, _audio_file = _build_panel(tmp_path)
    qtbot.addWidget(panel)
    calls = {"mark": 0}

    class _FakeDB:
        def get_session(self):
            raise AssertionError("DB session should not be requested without item_id")

    def _fake_mark_played(self, session, item_id, rate_used=1.0):  # noqa: ARG001
        calls["mark"] += 1

    monkeypatch.setattr("app.services.db_service.DBService.get_instance", lambda: _FakeDB())
    monkeypatch.setattr("app.services.audio_queue_service.AudioQueueService.mark_played", _fake_mark_played)

    panel._on_track_finished({"label": "x", "context": {"kind": "lemma"}})

    assert calls["mark"] == 0
