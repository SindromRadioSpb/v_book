from __future__ import annotations
import sys
from unittest.mock import MagicMock, patch

import pytest

from app.services.audio_player_service import _clamp_rate, AudioPlayerService


# -- Pure function tests (no QApp needed) ---------------------------------


def test_clamp_rate_normal():
    assert _clamp_rate(1.0) == 1.0


def test_clamp_rate_min():
    assert _clamp_rate(0.1) == 0.25


def test_clamp_rate_max():
    assert _clamp_rate(10.0) == 4.0


def test_clamp_rate_exact_bounds():
    assert _clamp_rate(0.25) == 0.25
    assert _clamp_rate(4.0) == 4.0


def test_clamp_rate_invalid():
    assert _clamp_rate("bad") == 1.0


# -- Service rate tests (require QApp) ------------------------------------


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtCore import QCoreApplication
    return QCoreApplication.instance() or QCoreApplication(sys.argv)


@pytest.fixture
def service(qapp):
    AudioPlayerService.reset_instance_for_tests()
    settings_mock = MagicMock()
    settings_mock.get_int.return_value = 0
    settings_mock.get_string.return_value = "1.0"
    settings_mock.get_bool.return_value = False
    with patch.object(AudioPlayerService, "_build_default_backend", return_value=None):
        svc = AudioPlayerService(settings=settings_mock)
    yield svc
    AudioPlayerService.reset_instance_for_tests()


def test_set_playback_rate_persists(service):
    service.set_playback_rate(0.75)
    assert service._playback_rate == 0.75


def test_set_playback_rate_clamps(service):
    service.set_playback_rate(10.0)
    assert service._playback_rate == 4.0


def test_get_playback_rate_default(service):
    # Default rate after construction with settings mock returning "1.0"
    assert service.get_playback_rate() == 1.0
