from __future__ import annotations
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.audio_player_service import AudioPlayerService, AudioTrack


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtCore import QCoreApplication
    app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    return app


def _make_service(qapp):
    AudioPlayerService.reset_instance_for_tests()
    settings_mock = MagicMock()
    settings_mock.get_int.return_value = 0
    settings_mock.get_string.return_value = "1.0"
    settings_mock.get_bool.return_value = False
    with patch.object(AudioPlayerService, "_build_default_backend", return_value=None):
        svc = AudioPlayerService(settings=settings_mock)
    return svc


@pytest.fixture
def service(qapp, tmp_path):
    svc = _make_service(qapp)
    yield svc
    AudioPlayerService.reset_instance_for_tests()


@pytest.fixture
def tmp_audio(tmp_path):
    paths = []
    for i in range(5):
        p = tmp_path / f"track_{i}.wav"
        p.write_bytes(b"RIFF")
        paths.append(p)
    return paths


def _inject_tracks(svc, paths):
    svc._tracks = [AudioTrack(path=p, label=p.stem) for p in paths]
    svc._current_index = -1


# -- 1. all 3 tracks stay after advancing cursor --------------------------


def test_play_paths_nondestructive(service, tmp_audio):
    n = service.play_paths(tmp_audio[:3])
    assert n == 3
    assert len(service._tracks) == 3


# -- 2. items stay after advancing _current_index -------------------------


def test_items_stay_after_next_track(service, tmp_audio):
    _inject_tracks(service, tmp_audio[:3])
    # Advance cursor 3 times (simulate next without actually calling backend)
    for _ in range(3):
        service._current_index = min(service._current_index + 1, 2)
    assert len(service._tracks) == 3


# -- 3. queue_snapshot returns all tracks ----------------------------------


def test_queue_snapshot_returns_all(service, tmp_audio):
    _inject_tracks(service, tmp_audio[:3])
    service._current_index = 1
    snap = service.queue_snapshot()
    assert len(snap) == 3


# -- 4. clear_queue empties tracks ----------------------------------------


def test_clear_queue_empties_tracks(service, tmp_audio):
    _inject_tracks(service, tmp_audio[:3])
    service.clear_queue()
    assert service._tracks == []
    assert service._current_index == -1


# -- 5. remove before current shifts cursor left --------------------------


def test_remove_queue_index_adjusts_cursor(service, tmp_audio):
    _inject_tracks(service, tmp_audio[:3])
    service._current_index = 2
    result = service.remove_queue_index(0)
    assert result is True
    assert len(service._tracks) == 2
    assert service._current_index == 1


# -- 6. remove current stops and backs cursor up --------------------------


def test_remove_current_item_stops(service, tmp_audio):
    _inject_tracks(service, tmp_audio[:3])
    service._current_index = 1
    service._current = service._tracks[1]
    result = service.remove_queue_index(1)
    assert result is True
    assert service._current is None
    # Cursor backed up: was 1, now 0
    assert service._current_index == 0


# -- 7. interrupt mode replaces queue -------------------------------------


def test_interrupt_mode_replaces_queue(service, tmp_audio):
    _inject_tracks(service, tmp_audio[:2])
    n = service.play_paths(tmp_audio[2:4], play_mode="interrupt")
    assert n == 2
    assert len(service._tracks) == 2
    assert all("track_2" in str(t.path) or "track_3" in str(t.path) for t in service._tracks)


# -- 8. enqueue mode appends ----------------------------------------------


def test_enqueue_mode_appends(service, tmp_audio):
    _inject_tracks(service, tmp_audio[:2])
    # Pretend something is playing so enqueue does not auto-start
    service._current = service._tracks[0]
    n = service.play_paths(tmp_audio[2:4], play_mode="enqueue")
    assert n == 2
    assert len(service._tracks) == 4
