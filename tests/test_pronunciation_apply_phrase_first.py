"""Phrase-first pronunciation application tests."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.domain.normalization.normalizer import normalize_for_tm
from app.infra.sa_models import PronunciationEntry
from app.services.pronunciation_service import PronunciationService


def _workspace_temp_dir(prefix: str) -> Path:
    root = Path("build") / "tmp_tests"
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=str(root)))


def test_apply_phrase_level_replacement_beats_token_only():
    temp_dir = _workspace_temp_dir("pron_phrase_")
    engine = create_engine(f"sqlite:///{temp_dir / 'pron.db'}")
    try:
        PronunciationEntry.__table__.create(engine, checkfirst=True)
        service = PronunciationService()
        phrase_norm = normalize_for_tm("he", "שלום בית", "surface").norm
        token_norm = normalize_for_tm("he", "בית", "surface").norm

        with Session(engine) as session:
            service.upsert_entry(
                session,
                lang="he",
                src_norm=token_norm,
                niqqud_text="בַּיִת",
                ipa=None,
                source="manual",
                is_override=True,
            )
            service.upsert_entry(
                session,
                lang="he",
                src_norm=phrase_norm,
                niqqud_text="שָׁלוֹם בַּיִת",
                ipa=None,
                source="manual",
                is_override=True,
            )
            session.commit()

            applied = service.apply_to_text(
                session,
                src_lang="he",
                source_text="שלום בית",
                source_norm=phrase_norm,
            )
            assert applied.mode in {"exact_text", "phrase_or_token"}
            assert applied.token_text == "שָׁלוֹם בַּיִת"
            assert "<speak" in applied.ssml
    finally:
        engine.dispose()
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_apply_token_fallback_when_phrase_missing():
    temp_dir = _workspace_temp_dir("pron_token_")
    engine = create_engine(f"sqlite:///{temp_dir / 'pron.db'}")
    try:
        PronunciationEntry.__table__.create(engine, checkfirst=True)
        service = PronunciationService()
        token_norm = normalize_for_tm("he", "בית", "surface").norm
        source_norm = normalize_for_tm("he", "שלום בית", "surface").norm

        with Session(engine) as session:
            service.upsert_entry(
                session,
                lang="he",
                src_norm=token_norm,
                niqqud_text="בַּיִת",
                ipa=None,
                source="manual",
                is_override=True,
            )
            session.commit()

            applied = service.apply_to_text(
                session,
                src_lang="he",
                source_text="שלום בית",
                source_norm=source_norm,
            )
            assert applied.mode == "phrase_or_token"
            assert applied.token_text == "שלום בַּיִת"
    finally:
        engine.dispose()
        shutil.rmtree(temp_dir, ignore_errors=True)
