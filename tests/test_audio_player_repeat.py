from __future__ import annotations
import sys
from unittest.mock import MagicMock, patch

import pytest

from app.services.audio_player_service import AudioPlayerService


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


# -- 1. default repeat mode -----------------------------------------------


def test_repeat_mode_default_none(service):
    assert service._repeat_mode == "none"


# -- 2. set repeat one ----------------------------------------------------


def test_set_repeat_mode_one(service):
    service.set_repeat_mode("one")
    assert service._repeat_mode == "one"


# -- 3. set repeat all ----------------------------------------------------


def test_set_repeat_mode_all(service):
    service.set_repeat_mode("all")
    assert service._repeat_mode == "all"


# -- 4. invalid mode defaults to none -------------------------------------


def test_set_repeat_mode_invalid_defaults_none(service):
    service.set_repeat_mode("bogus")
    assert service._repeat_mode == "none"


# -- 5. set repeat count --------------------------------------------------


def test_set_repeat_count(service):
    service.set_repeat_count(3)
    assert service._repeat_count == 3


# -- 6. negative repeat count clamped to 0 --------------------------------


def test_set_repeat_count_clamps_negative(service):
    service.set_repeat_count(-1)
    assert service._repeat_count == 0


# -- 7. auto_pause default false ------------------------------------------


def test_auto_pause_default_false(service):
    assert service._auto_pause is False


# -- 8. set auto_pause ----------------------------------------------------


def test_set_auto_pause(service):
    service.set_auto_pause(True)
    assert service._auto_pause is True
