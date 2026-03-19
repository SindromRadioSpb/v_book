"""Tests: manual override always wins; is_override=1 never auto-overwritten."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.infra.sa_models import SentencePronunciation
from app.services.sentence_pronunciation_service import SentencePronunciationService


@pytest.fixture()
def db_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/sp_manual.db")
    SentencePronunciation.__table__.create(engine, checkfirst=True)
    yield engine
    engine.dispose()


class TestManualOverrideWins:
    def test_auto_does_not_overwrite_manual(self, db_engine):
        svc = SentencePronunciationService()

        with Session(db_engine) as session:
            # 1) Save manual override
            svc.upsert_manual(
                session,
                sentence_id=1,
                niqqud_text="שָׁלוֹם עוֹלָם",
                notes="manually set",
            )
            session.commit()

            # 2) Attempt auto upsert (fill_only)
            hash_v = svc.compute_src_hash("he", "שלום עולם", "v1")
            action = svc.upsert_auto(
                session,
                sentence_id=1,
                lang="he",
                src_hash=hash_v,
                src_preprocessed="שלום עולם",
                niqqud_text="שַׁלּוֹם עוֹלָם (auto)",
                confidence=0.9,
                qc_status="ok",
                qc_reason=None,
                niqqud_coverage=0.9,
                phonikud_version="v1",
                mode="fill_only",
            )
            session.commit()

            assert action == "skipped_has_override"
            row = session.get(SentencePronunciation, 1)
            assert row.is_override == 1
            assert "manually set" in (row.qc_reason or "")
            assert "auto" not in (row.niqqud_text or "")

    def test_rebuild_does_not_overwrite_manual(self, db_engine):
        svc = SentencePronunciationService()

        with Session(db_engine) as session:
            svc.upsert_manual(
                session,
                sentence_id=2,
                niqqud_text="בְּרֵאשִׁית בָּרָא",
            )
            session.commit()

            hash_v = svc.compute_src_hash("he", "בראשית ברא", "v1")
            action = svc.upsert_auto(
                session,
                sentence_id=2,
                lang="he",
                src_hash=hash_v,
                src_preprocessed="בראשית ברא",
                niqqud_text="בְּרֵאשִׁית בָּרָא (rebuild)",
                confidence=0.85,
                qc_status="ok",
                qc_reason=None,
                niqqud_coverage=0.85,
                phonikud_version="v1",
                mode="rebuild",
            )
            session.commit()

            assert action == "skipped_has_override"
            row = session.get(SentencePronunciation, 2)
            assert row.is_override == 1
            assert "rebuild" not in (row.niqqud_text or "")

    def test_clear_removes_override_flag(self, db_engine):
        svc = SentencePronunciationService()

        with Session(db_engine) as session:
            svc.upsert_manual(session, sentence_id=3, niqqud_text="שָׁלוֹם")
            session.commit()

            svc.clear(session, sentence_id=3)
            session.commit()

            row = session.get(SentencePronunciation, 3)
            assert row is not None
            assert row.is_override == 0
            assert row.niqqud_text is None
            assert row.qc_status == "pending"

    def test_manual_upsert_sets_is_override(self, db_engine):
        svc = SentencePronunciationService()

        with Session(db_engine) as session:
            svc.upsert_manual(session, sentence_id=4, niqqud_text="שָׁלוֹם")
            session.commit()

            row = session.get(SentencePronunciation, 4)
            assert row.is_override == 1
            assert row.source == "manual"
            assert row.review_status == "approved"
