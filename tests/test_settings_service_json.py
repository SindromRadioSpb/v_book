"""Tests for SettingsService JSON compatibility guards."""

from app.infra.settings import SettingsService


class _BackendStub:
    def __init__(self, value):
        self._value = value

    def value(self, _key, _default=None, type=None):
        _ = type
        return self._value


def test_get_json_accepts_native_list_value():
    svc = SettingsService.__new__(SettingsService)
    svc._settings = _BackendStub(["google_cloud_tts", "azure_speech_tts"])

    value = svc.get_json("audio/providers/chain", [])
    assert value == ["google_cloud_tts", "azure_speech_tts"]


def test_get_json_parses_json_string():
    svc = SettingsService.__new__(SettingsService)
    svc._settings = _BackendStub('["a", "b"]')

    value = svc.get_json("k", [])
    assert value == ["a", "b"]
