"""Regression: latest regenerate must win in playback path resolution."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.infra.sa_models import AudioAsset
from app.services.audio_asset_service import AudioAssetService
from app.services.audio_playback_service import AudioPlaybackService


def _workspace_temp_dir(prefix: str) -> Path:
    root = Path("build") / "tmp_tests"
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=str(root)))


def test_latest_ready_after_provider_switch_wins(monkeypatch):
    temp_dir = _workspace_temp_dir("audio_latest_ready_")
    engine = create_engine(f"sqlite:///{temp_dir / 'audio.db'}")
    try:
        AudioAsset.__table__.create(engine, checkfirst=True)
        monkeypatch.setattr("app.services.audio_playback_service._get_app_dir", lambda: temp_dir)

        rel_google_first = "audio/google/he/first.wav"
        rel_mms = "audio/mms/he/middle.wav"
        rel_google_last = "audio/google/he/last.wav"
        for rel in (rel_google_first, rel_mms, rel_google_last):
            abs_path = temp_dir / Path(rel)
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_bytes(b"RIFF")

        service = AudioAssetService()
        timestamps = iter(
            [
                "2026-02-20T10:00:00.000000Z",
                "2026-02-20T10:01:00.000000Z",
                "2026-02-20T10:02:00.000000Z",
            ]
        )
        monkeypatch.setattr(service, "_now_str", lambda: next(timestamps))

        with Session(engine) as session:
            service.upsert_status(
                session=session,
                lang="he",
                norm_text="תחנה הבאה",
                provider="google_cloud_tts",
                status="ready",
                audio_rel_path=rel_google_first,
            )
            session.commit()

            service.upsert_status(
                session=session,
                lang="he",
                norm_text="תחנה הבאה",
                provider="mms_tts_local",
                status="ready",
                audio_rel_path=rel_mms,
            )
            session.commit()

            # Regenerate with Google again -> must become latest selected path.
            service.upsert_status(
                session=session,
                lang="he",
                norm_text="תחנה הבאה",
                provider="google_cloud_tts",
                status="ready",
                audio_rel_path=rel_google_last,
            )
            session.commit()

            resolved = AudioPlaybackService.resolve_ready_path(
                session,
                lang="he",
                norm_text="תחנה הבאה",
            )
            assert resolved == (temp_dir / rel_google_last)
    finally:
        engine.dispose()
        shutil.rmtree(temp_dir, ignore_errors=True)
