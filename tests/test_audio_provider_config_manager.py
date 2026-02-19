"""Tests for AudioProviderConfigManager advanced settings persistence."""

from __future__ import annotations

from app.infra.audio.audio_provider_config import AudioProviderAuthMode
from app.infra.audio.audio_provider_config_manager import AudioProviderConfigManager


class _SettingsStub:
    def __init__(self):
        self._data = {}

    def get_string(self, key: str, default: str = "") -> str:
        value = self._data.get(key, default)
        return str(value)

    def get_bool(self, key: str, default: bool = False) -> bool:
        value = self._data.get(key, default)
        return bool(value)

    def get_int(self, key: str, default: int = 0) -> int:
        value = self._data.get(key, default)
        try:
            return int(value)
        except Exception:
            return int(default)

    def set_value(self, key: str, value):
        self._data[key] = value

    def sync(self):
        return None


def test_google_audio_defaults_are_safe_and_disabled():
    settings = _SettingsStub()
    manager = AudioProviderConfigManager(settings=settings)

    cfg = manager.load_config("google_cloud_tts")
    assert cfg.enabled is False
    assert cfg.auth_mode == AudioProviderAuthMode.SERVICE_ACCOUNT_JSON
    assert cfg.max_chars_per_month == 500000
    assert cfg.max_requests_per_minute == 60
    assert cfg.fail_closed is True


def test_audio_config_persists_budget_and_retry_fields():
    settings = _SettingsStub()
    manager = AudioProviderConfigManager(settings=settings)

    cfg = manager.load_config("azure_speech_tts")
    cfg.enabled = True
    cfg.region = "westeurope"
    cfg.max_chars_per_request = 2500
    cfg.max_chars_per_day = 11111
    cfg.max_chars_per_month = 22222
    cfg.max_requests_per_minute = 12
    cfg.max_requests_per_day = 333
    cfg.fail_closed = True
    cfg.timeout_seconds = 21.0
    cfg.retry_max_attempts = 4
    cfg.retry_backoff_base_ms = 750
    cfg.default_voice = "he-IL-HilaNeural"
    cfg.speech_rate = 0.85

    manager.save_config(cfg)

    loaded = manager.load_config("azure_speech_tts")
    assert loaded.enabled is True
    assert loaded.region == "westeurope"
    assert loaded.max_chars_per_request == 2500
    assert loaded.max_chars_per_day == 11111
    assert loaded.max_chars_per_month == 22222
    assert loaded.max_requests_per_minute == 12
    assert loaded.max_requests_per_day == 333
    assert loaded.fail_closed is True
    assert int(loaded.timeout_seconds) == 21
    assert loaded.retry_max_attempts == 4
    assert loaded.retry_backoff_base_ms == 750
    assert loaded.default_voice == "he-IL-HilaNeural"
    assert abs(float(loaded.speech_rate) - 0.85) < 1e-6
