"""Tests for local MMS provider license gate behavior."""

from __future__ import annotations

from app.infra.audio.audio_provider_config import AudioProviderAuthMode, AudioProviderConfig
from app.infra.audio.audio_provider_config_manager import AudioProviderConfigManager
from app.infra.audio.base_provider import AudioErrorKind, AudioGenerationRequest
from app.infra.audio.providers.mms_tts_local_provider import MMSTTSLocalProvider


class _SettingsStub:
    def __init__(self, *, accepted: bool):
        self.accepted = accepted

    def get_bool(self, key: str, default: bool = False) -> bool:
        if key == MMSTTSLocalProvider.LICENSE_GATE_KEY:
            return self.accepted
        return default


class _ConfigManagerStub:
    def __init__(self, *, enabled: bool = True, model_path: str | None = None):
        self.enabled = enabled
        self.model_path = model_path

    def load_config(self, provider_id: str) -> AudioProviderConfig:
        return AudioProviderConfig(
            provider_id=provider_id,
            enabled=self.enabled,
            auth_mode=AudioProviderAuthMode.NONE,
            model_path=self.model_path,
        )


class _SettingsDefaultsStub:
    def get_string(self, _key: str, default: str = "") -> str:
        return default

    def get_bool(self, _key: str, default: bool = False) -> bool:
        return default

    def get_int(self, _key: str, default: int = 0) -> int:
        return default


def _request() -> AudioGenerationRequest:
    return AudioGenerationRequest(
        source_text="שלום",
        source_lang="he",
        source_norm="שלום",
        speed=1.0,
        voice_id="default",
    )


def test_mms_provider_blocks_when_license_not_accepted(monkeypatch):
    monkeypatch.setattr(
        "app.infra.audio.providers.mms_tts_local_provider.SettingsService.get_instance",
        lambda: _SettingsStub(accepted=False),
    )

    provider = MMSTTSLocalProvider(config_manager=_ConfigManagerStub(enabled=True))

    called = {"value": False}

    def _should_not_run(**_kwargs):
        called["value"] = True
        raise AssertionError("_synthesize must not run when license is not accepted")

    monkeypatch.setattr(provider, "_synthesize", _should_not_run)

    result = provider.generate(_request())

    assert result.error_kind == AudioErrorKind.UNSUPPORTED
    assert "license" in (result.error_message or "").lower()
    assert called["value"] is False


def test_mms_provider_blocks_when_disabled_even_if_license_accepted(monkeypatch):
    monkeypatch.setattr(
        "app.infra.audio.providers.mms_tts_local_provider.SettingsService.get_instance",
        lambda: _SettingsStub(accepted=True),
    )

    provider = MMSTTSLocalProvider(config_manager=_ConfigManagerStub(enabled=False))
    result = provider.generate(_request())

    assert result.error_kind == AudioErrorKind.UNSUPPORTED
    assert "disabled" in (result.error_message or "").lower()


def test_mms_provider_returns_unsupported_when_local_deps_missing(monkeypatch):
    monkeypatch.setattr(
        "app.infra.audio.providers.mms_tts_local_provider.SettingsService.get_instance",
        lambda: _SettingsStub(accepted=True),
    )

    provider = MMSTTSLocalProvider(config_manager=_ConfigManagerStub(enabled=True))

    def _raise_import(**_kwargs):
        raise ImportError("torch is not installed")

    monkeypatch.setattr(provider, "_synthesize", _raise_import)

    result = provider.generate(_request())

    assert result.error_kind == AudioErrorKind.UNSUPPORTED
    assert "dependencies" in (result.error_message or "").lower()


def test_mms_default_config_is_disabled():
    manager = AudioProviderConfigManager(settings=_SettingsDefaultsStub())
    cfg = manager.load_config("mms_tts_local")
    assert cfg.enabled is False
