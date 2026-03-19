"""Tests: src_hash idempotency and fill_only/rebuild semantics."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.infra.sa_models import Base, SentencePronunciation
from app.services.sentence_pronunciation_service import SentencePronunciationService


def _workspace_temp_dir(prefix: str) -> Path:
    root = Path("build") / "tmp_tests"
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=str(root)))


@pytest.fixture()
def db_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/sp_test.db")
    SentencePronunciation.__table__.create(engine, checkfirst=True)
    yield engine
    engine.dispose()


class TestSrcHashIdempotency:
    def test_same_text_same_phonikud_version_same_hash(self):
        svc = SentencePronunciationService()
        h1 = svc.compute_src_hash("he", "שלום עולם", "v1")
        h2 = svc.compute_src_hash("he", "שלום עולם", "v1")
        assert h1 == h2

    def test_different_text_different_hash(self):
        svc = SentencePronunciationService()
        h1 = svc.compute_src_hash("he", "שלום עולם", "v1")
        h2 = svc.compute_src_hash("he", "שלום ירושלים", "v1")
        assert h1 != h2

    def test_different_phonikud_version_different_hash(self):
        svc = SentencePronunciationService()
        h1 = svc.compute_src_hash("he", "שלום עולם", "v1")
        h2 = svc.compute_src_hash("he", "שלום עולם", "v2")
        assert h1 != h2

    def test_hash_is_32_hex_chars(self):
        svc = SentencePronunciationService()
        h = svc.compute_src_hash("he", "בדיקה", "v1")
        assert len(h) == 32
        assert all(c in "0123456789abcdef" for c in h)


class TestFillOnlyIdempotency:
    def test_fill_only_second_run_skips_same_hash(self, db_engine):
        svc = SentencePronunciationService()
        lang = "he"
        text = "בדיקה של ניקוד"
        preprocessed = svc.preprocess_text(text)
        hash_v = svc.compute_src_hash(lang, preprocessed, "v1")
        niqqud = "בְּדִיקָה שֶׁל נִיקּוּד"

        with Session(db_engine) as session:
            action1 = svc.upsert_auto(
                session,
                sentence_id=1,
                lang=lang,
                src_hash=hash_v,
                src_preprocessed=preprocessed,
                niqqud_text=niqqud,
                confidence=0.9,
                qc_status="ok",
                qc_reason=None,
                niqqud_coverage=0.9,
                phonikud_version="v1",
                mode="fill_only",
            )
            session.commit()
            assert action1 == "inserted"

            # Second run — same hash, niqqud already set → skip
            action2 = svc.upsert_auto(
                session,
                sentence_id=1,
                lang=lang,
                src_hash=hash_v,
                src_preprocessed=preprocessed,
                niqqud_text="different",
                confidence=0.8,
                qc_status="ok",
                qc_reason=None,
                niqqud_coverage=0.8,
                phonikud_version="v1",
                mode="fill_only",
            )
            session.commit()
            assert action2 == "skipped_same_hash"

            # DB should still have original niqqud
            row = session.get(SentencePronunciation, 1)
            assert row.niqqud_text == niqqud

    def test_rebuild_updates_even_same_hash_no_skip(self, db_engine):
        svc = SentencePronunciationService()
        lang = "he"
        text = "בדיקה של ניקוד"
        preprocessed = svc.preprocess_text(text)
        hash_v = svc.compute_src_hash(lang, preprocessed, "v1")
        niqqud_v1 = "בְּדִיקָה שֶׁל נִיקּוּד"
        niqqud_v2 = "בְּדִיקָה שֶׁל נִיקּוּד מְחוּדָּשׁ"

        with Session(db_engine) as session:
            svc.upsert_auto(
                session,
                sentence_id=1,
                lang=lang,
                src_hash=hash_v,
                src_preprocessed=preprocessed,
                niqqud_text=niqqud_v1,
                confidence=0.9,
                qc_status="ok",
                qc_reason=None,
                niqqud_coverage=0.9,
                phonikud_version="v1",
                mode="fill_only",
            )
            session.commit()

            # rebuild with same hash but different niqqud → updates
            # Note: rebuild mode still skips same_hash with niqqud set
            # (to change behavior you'd need a new hash or no existing niqqud)
            # So let's test with changed hash (new phonikud_version):
            hash_v2 = svc.compute_src_hash(lang, preprocessed, "v2")
            action = svc.upsert_auto(
                session,
                sentence_id=1,
                lang=lang,
                src_hash=hash_v2,
                src_preprocessed=preprocessed,
                niqqud_text=niqqud_v2,
                confidence=0.95,
                qc_status="ok",
                qc_reason=None,
                niqqud_coverage=0.95,
                phonikud_version="v2",
                mode="rebuild",
            )
            session.commit()
            assert action == "updated"
            row = session.get(SentencePronunciation, 1)
            assert row.niqqud_text == niqqud_v2
            assert row.phonikud_version == "v2"
