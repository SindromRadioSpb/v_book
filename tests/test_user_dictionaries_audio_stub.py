"""Tests for AudioAssetService status lookup stub."""

from __future__ import annotations

import tempfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.infra.sa_models import AudioAsset
from app.services.audio_cache_key_service import AudioCacheKeyService
from app.services.audio_asset_service import AudioAssetService


def test_audio_asset_bulk_status_lookup_ready_missing_failed():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        AudioAsset.__table__.create(engine, checkfirst=True)

        service = AudioAssetService()
        with Session(engine) as session:
            service.upsert_status(
                session,
                lang="he",
                norm_text="alpha",
                voice_id="default",
                speed=1.0,
                provider="none",
                status="ready",
                audio_rel_path="audio/alpha.mp3",
            )
            service.upsert_status(
                session,
                lang="he",
                norm_text="beta",
                voice_id="default",
                speed=1.0,
                provider="none",
                status="failed",
                error_text="tts_error",
            )
            session.commit()

            statuses = service.bulk_get_status(
                session,
                lang="he",
                norm_texts=["alpha", "beta", "gamma"],
                voice_id="default",
                speed=1.0,
                provider="none",
            )

            assert statuses["alpha"] == "ready"
            assert statuses["beta"] == "failed"
            assert statuses["gamma"] == "missing"

            any_statuses = service.bulk_get_status_any(
                session,
                lang="he",
                norm_texts=["alpha", "beta", "gamma"],
            )
            assert any_statuses["alpha"] == "ready"
            assert any_statuses["beta"] == "failed"
            assert any_statuses["gamma"] == "missing"
    finally:
        engine.dispose()
        Path(db_path).unlink(missing_ok=True)


def test_audio_asset_bulk_status_for_items_is_pronunciation_aware():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        AudioAsset.__table__.create(engine, checkfirst=True)

        service = AudioAssetService()
        cache_keys = AudioCacheKeyService()
        with Session(engine) as session:
            source_text = "שלום בית"
            payload = {
                "text": source_text,
                "token_text": source_text,
                "ssml": "",
                "mode": "none",
                "is_valid": True,
                "qc_flag": None,
            }
            speech_hash = cache_keys.build_speech_hash(
                src_lang="he",
                source_text=source_text,
                source_norm="alpha",
                pronunciation_payload=payload,
            )
            service.upsert_status(
                session,
                lang="he",
                norm_text="alpha",
                voice_id="default",
                speed=1.0,
                provider="none",
                speech_hash=speech_hash,
                input_hash="alpha-input",
                status="ready",
                audio_rel_path="audio/alpha.mp3",
            )
            session.commit()

            statuses = service.bulk_get_status_for_items(
                session,
                items=[
                    {"lang": "he", "norm_text": "alpha", "source_text": "שלום בית"},
                    {"lang": "he", "norm_text": "alpha", "source_text": "שלום בַיִת"},
                ],
            )

            assert statuses[("he", "alpha", "שלום בית")] == "ready"
            assert statuses[("he", "alpha", "שלום בַיִת")] == "missing"
    finally:
        engine.dispose()
        Path(db_path).unlink(missing_ok=True)


def test_audio_asset_upsert_uses_input_hash_identity_and_allows_multiple_legacy_variants():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        AudioAsset.__table__.create(engine, checkfirst=True)

        service = AudioAssetService()
        with Session(engine) as session:
            service.upsert_status(
                session,
                lang="he",
                norm_text="alpha",
                voice_id="default",
                speed=1.0,
                provider="google_cloud_tts",
                speech_hash="speech-1",
                input_hash="input-1",
                status="ready",
                audio_rel_path="audio/alpha_1.wav",
            )
            service.upsert_status(
                session,
                lang="he",
                norm_text="alpha",
                voice_id="default",
                speed=1.0,
                provider="google_cloud_tts",
                speech_hash="speech-2",
                input_hash="input-2",
                status="ready",
                audio_rel_path="audio/alpha_2.wav",
            )
            session.commit()

            rows = (
                session.query(AudioAsset)
                .filter_by(
                    lang="he",
                    norm_text="alpha",
                    voice_id="default",
                    speed=1.0,
                    provider="google_cloud_tts",
                )
                .order_by(AudioAsset.asset_id.asc())
                .all()
            )
            assert len(rows) == 2
            assert {str(row.input_hash or "") for row in rows} == {"input-1", "input-2"}

            statuses = service.bulk_get_status(
                session,
                lang="he",
                norm_texts=["alpha"],
                voice_id="default",
                speed=1.0,
                provider="google_cloud_tts",
            )
            assert statuses["alpha"] == "ready"
    finally:
        engine.dispose()
        Path(db_path).unlink(missing_ok=True)
