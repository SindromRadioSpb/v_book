"""Audio generation integration with pronunciation layer."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.domain.normalization.normalizer import normalize_for_tm
from app.infra.audio.base_provider import (
    AudioGenerationRequest,
    AudioGenerationResult,
    BaseAudioProvider,
)
from app.infra.audio.providers_registry import AudioProvidersRegistry
from app.infra.sa_models import AudioAsset, PronunciationEntry
from app.services.audio_generation_service import AudioGenerationService
from app.services.pronunciation_service import PronunciationService


class _SettingsStub:
    def get_string(self, key: str, default: str = "") -> str:
        if key == "audio/voice_id":
            return "default"
        if key == "audio/speed":
            return "1.0"
        return default

    def get_json(self, key: str, default):
        if key == "audio/providers/chain":
            return ["capture_provider"]
        return default

    def get_bool(self, _key: str, default: bool = False) -> bool:
        if _key == "audio/providers/enabled":
            return True
        if _key == "audio/providers/google_cloud_tts/enabled":
            return True
        return default

    def get_int(self, _key: str, default: int = 0) -> int:
        return default


class _CaptureProvider(BaseAudioProvider):
    last_request: AudioGenerationRequest | None = None

    @property
    def provider_id(self) -> str:
        return "capture_provider"

    @property
    def display_name(self) -> str:
        return "Capture Provider"

    def generate(self, request: AudioGenerationRequest) -> AudioGenerationResult:
        _CaptureProvider.last_request = request
        return AudioGenerationResult(
            provider_id=self.provider_id,
            audio_bytes=b"RIFF....",
            mime_type="audio/wav",
        )


class _CaptureGoogleProvider(BaseAudioProvider):
    last_request: AudioGenerationRequest | None = None

    @property
    def provider_id(self) -> str:
        return "google_cloud_tts"

    @property
    def display_name(self) -> str:
        return "Capture Google"

    def generate(self, request: AudioGenerationRequest) -> AudioGenerationResult:
        _CaptureGoogleProvider.last_request = request
        return AudioGenerationResult(
            provider_id=self.provider_id,
            audio_bytes=b"RIFF....",
            mime_type="audio/wav",
        )


def _workspace_temp_dir(prefix: str) -> Path:
    root = Path("build") / "tmp_tests"
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=str(root)))


def _setup_registry(monkeypatch, provider):
    monkeypatch.setattr(
        "app.services.audio_generation_service.register_default_audio_providers", lambda: 0
    )
    AudioProvidersRegistry.reset()
    registry = AudioProvidersRegistry()
    registry.register(provider)


def test_token_pronunciation_substitution_for_non_ssml_provider(monkeypatch):
    temp_dir = _workspace_temp_dir("audio_pron_token_")
    engine = create_engine(f"sqlite:///{temp_dir / 'audio.db'}")
    try:
        AudioAsset.__table__.create(engine, checkfirst=True)
        PronunciationEntry.__table__.create(engine, checkfirst=True)
        monkeypatch.setattr("app.services.audio_generation_service._get_app_dir", lambda: temp_dir)
        _setup_registry(monkeypatch, _CaptureProvider())

        service = AudioGenerationService(settings=_SettingsStub())
        pron = PronunciationService()

        with Session(engine) as session:
            token_norm = normalize_for_tm("he", "בית", "surface").norm
            pron.upsert_entry(
                session,
                lang="he",
                src_norm=token_norm,
                niqqud_text="בַּיִת",
                ipa=None,
                source="manual",
                is_override=True,
                notes=None,
            )
            session.commit()

            result = service.generate_one(
                session,
                src_text="שלום בית",
                src_lang="he",
                source_norm=normalize_for_tm("he", "שלום בית", "surface").norm,
                provider_mode="force:capture_provider",
                trace_id="pron-token",
            )
            session.commit()

            assert result["ok"] is True
            assert _CaptureProvider.last_request is not None
            assert _CaptureProvider.last_request.source_text == "שלום בַּיִת"
            assert not _CaptureProvider.last_request.options
    finally:
        engine.dispose()
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_ssml_payload_used_for_google_provider(monkeypatch):
    temp_dir = _workspace_temp_dir("audio_pron_ssml_")
    engine = create_engine(f"sqlite:///{temp_dir / 'audio.db'}")
    try:
        AudioAsset.__table__.create(engine, checkfirst=True)
        PronunciationEntry.__table__.create(engine, checkfirst=True)
        monkeypatch.setattr("app.services.audio_generation_service._get_app_dir", lambda: temp_dir)
        _setup_registry(monkeypatch, _CaptureGoogleProvider())

        service = AudioGenerationService(settings=_SettingsStub())
        pron = PronunciationService()
        with Session(engine) as session:
            source_norm = normalize_for_tm("he", "שלום", "surface").norm
            pron.upsert_entry(
                session,
                lang="he",
                src_norm=source_norm,
                niqqud_text=None,
                ipa="ʃaˈlom",
                source="manual",
                is_override=True,
                notes=None,
            )
            session.commit()

            result = service.generate_one(
                session,
                src_text="שלום",
                src_lang="he",
                source_norm=source_norm,
                provider_mode="force:google_cloud_tts",
                trace_id="pron-ssml",
            )
            session.commit()

            assert result["ok"] is True
            assert _CaptureGoogleProvider.last_request is not None
            ssml = (_CaptureGoogleProvider.last_request.options or {}).get("ssml", "")
            assert "<phoneme" in str(ssml)
    finally:
        engine.dispose()
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_source_payload_sanitizer_removes_taamim_and_bidi_chars(monkeypatch):
    temp_dir = _workspace_temp_dir("audio_pron_sanitize_")
    engine = create_engine(f"sqlite:///{temp_dir / 'audio.db'}")
    try:
        AudioAsset.__table__.create(engine, checkfirst=True)
        monkeypatch.setattr("app.services.audio_generation_service._get_app_dir", lambda: temp_dir)
        _setup_registry(monkeypatch, _CaptureProvider())

        service = AudioGenerationService(settings=_SettingsStub())
        raw_source = (
            "\u05E8\u05B7\u05AB\u05DB\u05B6\u05D1\u200F_\u200D-\u05DE\u05D4\u05D9\u05E8\u05D5\u05EA"
        )
        with Session(engine) as session:
            result = service.generate_one(
                session,
                src_text=raw_source,
                src_lang="he",
                source_norm=normalize_for_tm("he", raw_source, "surface").norm,
                provider_mode="force:capture_provider",
                trace_id="pron-sanitize",
            )
            session.commit()

            assert result["ok"] is True
            assert _CaptureProvider.last_request is not None
            payload = _CaptureProvider.last_request.source_text
            assert "\u05AB" not in payload
            assert "\u200F" not in payload
            assert "\u200D" not in payload
            assert "_" not in payload
            assert "-" not in payload
            assert "\u05B7" in payload
            assert "\u05B6" in payload
    finally:
        engine.dispose()
        shutil.rmtree(temp_dir, ignore_errors=True)
