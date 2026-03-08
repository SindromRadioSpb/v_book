"""Tests for audio playback path resolution safety."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.normalization.normalizer import normalize_for_tm
from app.infra.sa_models import AudioAsset
from app.services.audio_cache_key_service import AudioCacheKeyService
from app.services.audio_playback_service import AudioPlaybackService


def _workspace_temp_dir(prefix: str) -> Path:
    root = Path("build") / "tmp_tests"
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=str(root)))


def _insert_asset(
    session: Session,
    *,
    lang: str,
    norm_text: str,
    rel_path: str,
    status: str = "ready",
) -> None:
    session.add(
        AudioAsset(
            lang=lang,
            norm_text=norm_text,
            voice_id="default",
            speed=1.0,
            provider="mock_local_audio",
            asset_status=status,
            audio_rel_path=rel_path,
        )
    )
    session.flush()


def test_resolve_ready_path_returns_existing_relative_asset(monkeypatch):
    temp_dir = _workspace_temp_dir("audio_playback_ok_")
    engine = create_engine(f"sqlite:///{temp_dir / 'audio.db'}")
    try:
        AudioAsset.__table__.create(engine, checkfirst=True)
        rel = Path("audio/mock_local_audio/he/sample.wav")
        abs_path = temp_dir / rel
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_bytes(b"RIFF")

        monkeypatch.setattr("app.services.audio_playback_service._get_app_dir", lambda: temp_dir)

        with Session(engine) as session:
            _insert_asset(session, lang="he", norm_text="shalom", rel_path=str(rel).replace("\\", "/"))
            session.commit()
            resolved = AudioPlaybackService.resolve_ready_path(
                session,
                lang="he",
                norm_text="shalom",
            )
            assert resolved == abs_path
    finally:
        engine.dispose()
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_audio_asset_rel_path_constraint_rejects_unsafe_paths():
    temp_dir = _workspace_temp_dir("audio_playback_safe_")
    engine = create_engine(f"sqlite:///{temp_dir / 'audio.db'}")
    try:
        AudioAsset.__table__.create(engine, checkfirst=True)
        with Session(engine) as session:
            with pytest.raises(IntegrityError):
                _insert_asset(session, lang="he", norm_text="bad_abs", rel_path="C:/temp/evil.wav")
                session.commit()

            session.rollback()
            with pytest.raises(IntegrityError):
                _insert_asset(session, lang="he", norm_text="bad_parent", rel_path="audio/../evil.wav")
                session.commit()
    finally:
        engine.dispose()
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_resolve_ready_path_returns_none_when_file_missing(monkeypatch):
    temp_dir = _workspace_temp_dir("audio_playback_missing_")
    engine = create_engine(f"sqlite:///{temp_dir / 'audio.db'}")
    try:
        AudioAsset.__table__.create(engine, checkfirst=True)
        monkeypatch.setattr("app.services.audio_playback_service._get_app_dir", lambda: temp_dir)

        with Session(engine) as session:
            _insert_asset(session, lang="he", norm_text="missing_file", rel_path="audio/mock_local_audio/he/nope.wav")
            session.commit()

            assert AudioPlaybackService.resolve_ready_path(session, lang="he", norm_text="missing_file") is None
    finally:
        engine.dispose()
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_resolve_ready_path_ignores_stale_norm_match_when_source_text_changes(monkeypatch):
    temp_dir = _workspace_temp_dir("audio_playback_hash_guard_")
    engine = create_engine(f"sqlite:///{temp_dir / 'audio.db'}")
    try:
        AudioAsset.__table__.create(engine, checkfirst=True)
        monkeypatch.setattr("app.services.audio_playback_service._get_app_dir", lambda: temp_dir)
        cache_keys = AudioCacheKeyService()

        rel = Path("audio/mock_local_audio/he/stale.wav")
        abs_path = temp_dir / rel
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_bytes(b"RIFF")

        with Session(engine) as session:
            old_text = "שלום בית"
            norm_text = normalize_for_tm("he", old_text, "surface").norm
            old_payload = {
                "text": old_text,
                "token_text": old_text,
                "ssml": "",
                "mode": "none",
                "is_valid": True,
                "qc_flag": None,
            }
            speech_hash = cache_keys.build_speech_hash(
                src_lang="he",
                source_text=old_text,
                source_norm=norm_text,
                pronunciation_payload=old_payload,
            )
            _insert_asset(
                session,
                lang="he",
                norm_text=norm_text,
                rel_path=str(rel).replace("\\", "/"),
            )
            row = session.query(AudioAsset).filter_by(lang="he", norm_text=norm_text).one()
            row.speech_hash = speech_hash
            row.input_hash = "legacy-input"
            session.commit()

            resolved = AudioPlaybackService.resolve_ready_path(
                session,
                lang="he",
                norm_text=norm_text,
                source_text="שלום בַיִת",
            )
            assert resolved is None
    finally:
        engine.dispose()
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_launch_audio_files_passes_contexts_to_internal_player(monkeypatch, tmp_path):
    """Internal player path keeps per-track contexts so Audio Player queue can show metadata."""
    audio_file = tmp_path / "sample.wav"
    audio_file.write_bytes(b"RIFF")

    captured = {}

    class _FakePlayer:
        is_available = True

        def play_paths(self, paths, *, labels=None, play_mode=None, contexts=None, start_immediately=False):
            captured["paths"] = list(paths)
            captured["labels"] = list(labels or [])
            captured["play_mode"] = play_mode
            captured["contexts"] = list(contexts or [])
            captured["start_immediately"] = bool(start_immediately)
            return len(paths)

    monkeypatch.setattr(
        "app.services.audio_player_service.AudioPlayerService.get_instance",
        staticmethod(lambda: _FakePlayer()),
    )

    result = AudioPlaybackService.launch_audio_files(
        [audio_file],
        labels=["שלום"],
        play_mode="enqueue",
        contexts=[
            {
                "snapshot_hebrew": "שלום",
                "snapshot_source_label": "Dictionary",
                "snapshot_translation": "peace",
            }
        ],
    )

    assert result == 1
    assert captured["paths"] == [audio_file]
    assert captured["labels"] == ["שלום"]
    assert captured["play_mode"] == "enqueue"
    assert captured["start_immediately"] is False
    assert captured["contexts"][0]["snapshot_source_label"] == "Dictionary"
