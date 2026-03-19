"""Audio provider-chain fallback tests."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.infra.audio.base_provider import (
    AudioErrorKind,
    AudioGenerationRequest,
    AudioGenerationResult,
    BaseAudioProvider,
)
from app.infra.audio.providers_registry import AudioProvidersRegistry
from app.infra.sa_models import AudioAsset
from app.services.audio_generation_service import AudioGenerationService


class _SettingsStub:
    def __init__(self, enabled_map=None):
        self.enabled_map = enabled_map or {}

    def get_string(self, key: str, default: str = "") -> str:
        if key == "audio/voice_id":
            return "default"
        if key == "audio/speed":
            return "1.0"
        return default

    def get_json(self, key: str, default):
        if key == "audio/providers/chain":
            return ["provider_primary", "provider_secondary"]
        return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        if key in self.enabled_map:
            return bool(self.enabled_map[key])
        return default

    def get_int(self, _key: str, default: int = 0) -> int:
        return default


class _PrimaryFailProvider(BaseAudioProvider):
    calls = 0

    @property
    def provider_id(self) -> str:
        return "provider_primary"

    @property
    def display_name(self) -> str:
        return "Primary"

    def generate(self, _request: AudioGenerationRequest) -> AudioGenerationResult:
        _PrimaryFailProvider.calls += 1
        return AudioGenerationResult(
            provider_id=self.provider_id,
            error_kind=AudioErrorKind.RATE_LIMIT,
            error_message="429",
        )


class _SecondaryOkProvider(BaseAudioProvider):
    calls = 0

    @property
    def provider_id(self) -> str:
        return "provider_secondary"

    @property
    def display_name(self) -> str:
        return "Secondary"

    def generate(self, _request: AudioGenerationRequest) -> AudioGenerationResult:
        _SecondaryOkProvider.calls += 1
        return AudioGenerationResult(
            provider_id=self.provider_id,
            audio_bytes=b"RIFF....",
            mime_type="audio/wav",
        )


def _workspace_temp_dir(prefix: str) -> Path:
    root = Path("build") / "tmp_tests"
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=str(root)))


def _prepare_service(monkeypatch, settings):
    monkeypatch.setattr(
        "app.services.audio_generation_service.register_default_audio_providers", lambda: 0
    )
    registry = AudioProvidersRegistry()
    registry.reset()
    registry = AudioProvidersRegistry()
    registry.register(_PrimaryFailProvider())
    registry.register(_SecondaryOkProvider())
    return AudioGenerationService(settings=settings)


def test_chain_fallback_uses_secondary_when_primary_fails(monkeypatch):
    temp_dir = _workspace_temp_dir("audio_chain_")
    try:
        db_path = temp_dir / "audio.db"
        engine = create_engine(f"sqlite:///{db_path}")
        AudioAsset.__table__.create(engine, checkfirst=True)
        monkeypatch.setattr("app.services.audio_generation_service._get_app_dir", lambda: temp_dir)

        _PrimaryFailProvider.calls = 0
        _SecondaryOkProvider.calls = 0
        service = _prepare_service(monkeypatch, _SettingsStub())
        with Session(engine) as session:
            result = service.generate_one(
                session,
                src_text="shalom",
                src_lang="he",
                source_norm="shalom",
                provider_mode="chain",
                trace_id="chain-fallback",
            )
            session.commit()

            assert result["ok"] is True
            assert result["provider_id"] == "provider_secondary"
            assert _PrimaryFailProvider.calls == 1
            assert _SecondaryOkProvider.calls == 1
    finally:
        try:
            engine.dispose()
        except Exception:
            pass
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_chain_skips_disabled_provider(monkeypatch):
    temp_dir = _workspace_temp_dir("audio_chain_disabled_")
    try:
        db_path = temp_dir / "audio_disabled.db"
        engine = create_engine(f"sqlite:///{db_path}")
        AudioAsset.__table__.create(engine, checkfirst=True)
        monkeypatch.setattr("app.services.audio_generation_service._get_app_dir", lambda: temp_dir)

        _PrimaryFailProvider.calls = 0
        _SecondaryOkProvider.calls = 0
        settings = _SettingsStub(enabled_map={"audio/providers/provider_primary/enabled": False})
        service = _prepare_service(monkeypatch, settings)
        with Session(engine) as session:
            result = service.generate_one(
                session,
                src_text="shalom",
                src_lang="he",
                source_norm="shalom",
                provider_mode="chain",
                trace_id="chain-disabled",
            )
            session.commit()

            assert result["ok"] is True
            assert result["provider_id"] == "provider_secondary"
            assert _PrimaryFailProvider.calls == 0
            assert _SecondaryOkProvider.calls == 1
    finally:
        try:
            engine.dispose()
        except Exception:
            pass
        shutil.rmtree(temp_dir, ignore_errors=True)
