from __future__ import annotations

import sys

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
    def play(self, path):  # noqa: ANN001
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
def panel(qtbot):
    settings = _SettingsStub()
    player = AudioPlayerService(settings=settings, backend=_FakeBackend())
    widget = AudioPlayerPanel(player=player)
    qtbot.addWidget(widget)
    return widget


def test_action_policy_go_to_source_blocked_on_multi_select(panel):
    summary = {
        "count": 2,
        "single": False,
        "multi": True,
        "has_selection": True,
        "single_info": None,
        "single_kind": None,
        "single_status": None,
        "single_has_source_payload": False,
        "any_ready": False,
        "any_stale": False,
        "any_missing": True,
    }
    states = panel._compute_action_state("queue", summary, has_current_source=False)  # noqa: SLF001
    assert states["go_to_source"]["enabled"] is False
    assert "exactly one" in states["go_to_source"]["reason"].lower()


def test_action_policy_playlist_play_selected_requires_ready(panel):
    summary_missing = {
        "count": 1,
        "single": True,
        "multi": False,
        "has_selection": True,
        "single_info": {"row": 0, "kind": "term", "status": "missing", "has_source_payload": True},
        "single_kind": "term",
        "single_status": "missing",
        "single_has_source_payload": True,
        "any_ready": False,
        "any_stale": False,
        "any_missing": True,
    }
    states_missing = panel._compute_action_state(  # noqa: SLF001
        "playlist",
        summary_missing,
        has_current_source=False,
        has_playlist=True,
        playlist_entry_count=5,
        playlist_any_ready=True,
        queue_selection_count=0,
    )
    assert states_missing["playlist_play_selected"]["enabled"] is False

    summary_ready = dict(summary_missing)
    summary_ready.update(
        {
            "single_info": {
                "row": 0,
                "kind": "term",
                "status": "ready",
                "has_source_payload": True,
            },
            "single_status": "ready",
            "any_ready": True,
            "any_missing": False,
        }
    )
    states_ready = panel._compute_action_state(  # noqa: SLF001
        "playlist",
        summary_ready,
        has_current_source=False,
        has_playlist=True,
        playlist_entry_count=5,
        playlist_any_ready=True,
        queue_selection_count=0,
    )
    assert states_ready["playlist_play_selected"]["enabled"] is True


def test_action_policy_history_play_selected_requires_ready(panel):
    summary = {
        "count": 1,
        "single": True,
        "multi": False,
        "has_selection": True,
        "single_info": {"row": 0, "kind": "lemma", "status": "stale", "has_source_payload": True},
        "single_kind": "lemma",
        "single_status": "stale",
        "single_has_source_payload": True,
        "any_ready": False,
        "any_stale": True,
        "any_missing": False,
    }
    states = panel._compute_action_state(
        "history", summary, has_current_source=False
    )  # noqa: SLF001
    assert states["history_play_selected"]["enabled"] is False
    assert "playable" in states["history_play_selected"]["reason"].lower()
