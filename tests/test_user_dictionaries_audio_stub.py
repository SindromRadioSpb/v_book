"""Tests for AudioAssetService status lookup stub."""

from __future__ import annotations

import tempfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.infra.sa_models import AudioAsset
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
    finally:
        engine.dispose()
        Path(db_path).unlink(missing_ok=True)
