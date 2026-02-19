"""Tests for source-only audio generation service."""

from __future__ import annotations

import tempfile
import shutil
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.infra.sa_models import AudioAsset
from app.services.audio_generation_service import AudioGenerationService


class _DummySettings:
    def get_string(self, key: str, default: str = "") -> str:
        if key == "audio/voice_id":
            return "default"
        if key == "audio/speed":
            return "1.0"
        return default

    def get_json(self, _key: str, default):
        return default

    def get_bool(self, _key: str, default: bool = False) -> bool:
        return default

    def get_int(self, _key: str, default: int = 0) -> int:
        return default


class _AudioDisabledSettings(_DummySettings):
    def get_bool(self, key: str, default: bool = False) -> bool:
        if key == "audio/providers/enabled":
            return False
        return super().get_bool(key, default)


def _workspace_temp_dir(prefix: str) -> Path:
    root = Path("build") / "tmp_tests"
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=str(root)))


def test_generate_one_creates_ready_asset_and_skips_when_exists(monkeypatch):
    temp_audio_dir = _workspace_temp_dir("audio_gen_")
    db_path = temp_audio_dir / "audio_gen.db"

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        AudioAsset.__table__.create(engine, checkfirst=True)
        monkeypatch.setattr("app.services.audio_generation_service._get_app_dir", lambda: temp_audio_dir)

        service = AudioGenerationService(settings=_DummySettings())
        with Session(engine) as session:
            result = service.generate_one(
                session,
                src_text="shalom",
                src_lang="he",
                source_norm="shalom",
                provider_mode="force:mock_local_audio",
                force_regenerate=False,
                trace_id="t-audio-1",
            )
            session.commit()

            assert result["ok"] is True
            assert result["status"] == "ready"
            assert result["provider_id"] == "mock_local_audio"

            row = session.execute(select(AudioAsset).where(AudioAsset.norm_text == "shalom")).scalar_one()
            assert row.asset_status == "ready"
            assert row.audio_rel_path
            assert not Path(str(row.audio_rel_path)).is_absolute()
            assert (temp_audio_dir / row.audio_rel_path).exists()

            result_again = service.generate_one(
                session,
                src_text="shalom",
                src_lang="he",
                source_norm="shalom",
                provider_mode="force:mock_local_audio",
                force_regenerate=False,
                trace_id="t-audio-2",
            )
            assert result_again["ok"] is True
            assert result_again["status"] == "skipped"
    finally:
        engine.dispose()
        shutil.rmtree(temp_audio_dir, ignore_errors=True)


def test_generate_one_rejects_invalid_source_payload(monkeypatch):
    temp_audio_dir = _workspace_temp_dir("audio_invalid_")
    db_path = temp_audio_dir / "audio_invalid.db"

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        AudioAsset.__table__.create(engine, checkfirst=True)
        monkeypatch.setattr("app.services.audio_generation_service._get_app_dir", lambda: temp_audio_dir)

        service = AudioGenerationService(settings=_DummySettings())
        with Session(engine) as session:
            result = service.generate_one(
                session,
                src_text="",
                src_lang="he",
                source_norm="",
                provider_mode="chain",
                force_regenerate=False,
                trace_id="t-audio-invalid",
            )
            assert result["ok"] is False
            assert result["status"] == "failed"

            count = int(session.execute(select(func.count(AudioAsset.asset_id))).scalar() or 0)
            assert count == 0
    finally:
        engine.dispose()
        shutil.rmtree(temp_audio_dir, ignore_errors=True)


def test_generate_one_records_failed_status_when_provider_chain_unavailable(monkeypatch):
    temp_audio_dir = _workspace_temp_dir("audio_no_provider_")
    db_path = temp_audio_dir / "audio_no_provider.db"

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        AudioAsset.__table__.create(engine, checkfirst=True)
        monkeypatch.setattr("app.services.audio_generation_service._get_app_dir", lambda: temp_audio_dir)

        service = AudioGenerationService(settings=_AudioDisabledSettings())
        with Session(engine) as session:
            result = service.generate_one(
                session,
                src_text="shalom",
                src_lang="he",
                source_norm="shalom",
                provider_mode="chain",
                force_regenerate=False,
                trace_id="t-audio-no-provider",
            )
            session.commit()

            assert result["ok"] is False
            assert result["status"] == "failed"
            assert "No audio provider available" in str(result["error"])

            row = session.execute(select(AudioAsset).where(AudioAsset.norm_text == "shalom")).scalar_one()
            assert row.asset_status == "failed"
            assert "No audio provider available" in str(row.error_text)
    finally:
        engine.dispose()
        shutil.rmtree(temp_audio_dir, ignore_errors=True)
