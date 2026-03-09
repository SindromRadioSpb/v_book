"""Tests: bootstrap pipeline skip reason counters and dry_run semantics."""
from __future__ import annotations

from typing import Dict, List, Optional
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.infra.sa_models import DocumentSentence, SentencePronunciation, SourceDocument, SourceCorpus
from app.services.sentence_pronunciation_bootstrap_service import (
    GuardParams,
    SentencePronunciationBootstrapService,
)
from app.services.sentence_pronunciation_service import SentencePronunciationService


class _FakeGenerator:
    """Generator that returns Hebrew nikud for any input.

    Appends PATAH (U+05B7) to each Hebrew word so has_hebrew_nikud passes AND
    niqqud_coverage is high enough for QC status 'ok'.
    """

    mode = "real"

    def generate(self, lang: str, texts: List[str]) -> Dict[str, Dict]:
        result = {}
        for text in texts:
            words = text.split()
            nikud_words = []
            for w in words:
                # Append nikud mark to words containing Hebrew letters
                if any("\u05D0" <= c <= "\u05EA" for c in w):
                    nikud_words.append(w + "\u05B7")  # PATAH appended → has nikud
                else:
                    nikud_words.append(w)
            result[text] = {
                "niqqud_text": " ".join(nikud_words),
                "confidence": 0.85,
            }
        return result

    def health_check(self, *args, **kwargs):
        r = MagicMock()
        r.mode = "real"
        r.status = "ok"
        r.latency_ms = 10
        return r


class _NoNiqqudGenerator(_FakeGenerator):
    """Generator that returns text WITHOUT nikud (all results should be rejected)."""

    def generate(self, lang: str, texts: List[str]) -> Dict[str, Dict]:
        return {text: {"niqqud_text": text, "confidence": 0.1} for text in texts}


class _ModeSwitchingGenerator(_FakeGenerator):
    """Starts in fallback and reports real mode after first generation."""

    mode = "fallback"

    def generate(self, lang: str, texts: List[str]) -> Dict[str, Dict]:
        self.mode = "real"
        return super().generate(lang, texts)


@pytest.fixture()
def db_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/sp_bootstrap.db")
    # Create only the sentence_pronunciation table; inject sentence texts via workspace svc mock
    SentencePronunciation.__table__.create(engine, checkfirst=True)
    yield engine
    engine.dispose()


def _make_svc():
    return SentencePronunciationBootstrapService(chunk_size=100, sub_chunk_size=10)


class TestDryRunNoWrite:
    def test_dry_run_no_db_changes(self, db_engine, monkeypatch):
        from app.services import sentences_workspace_service as ws_module
        monkeypatch.setattr(
            ws_module.SentencesWorkspaceService,
            "get_sentence_texts_by_ids",
            lambda self, session, ids: {i: f"בית הספר מספר {i}" for i in ids},
        )

        svc = _make_svc()
        with Session(db_engine) as session:
            result = svc.run(
                session,
                list(range(1, 11)),
                lang="he",
                mode="dry_run",
                phonikud_generator=_FakeGenerator(),
            )
            # No commit issued inside dry_run path; verify no rows
            rows = session.query(SentencePronunciation).all()
        assert result.dry_run is True
        assert len(rows) == 0


class TestSkipReasonBuckets:
    def test_too_short_sentences_skipped(self, db_engine, monkeypatch):
        from app.services import sentences_workspace_service as ws_module
        monkeypatch.setattr(
            ws_module.SentencesWorkspaceService,
            "get_sentence_texts_by_ids",
            lambda self, session, ids: {i: "אב" for i in ids},  # 2 chars, below min
        )

        svc = _make_svc()
        guard = GuardParams(min_len=5)
        with Session(db_engine) as session:
            result = svc.run(
                session, [1, 2, 3], lang="he", mode="fill_only",
                phonikud_generator=_FakeGenerator(), guard_params=guard,
            )
            session.commit()

        assert result.skipped_too_short == 3
        assert result.inserted == 0

    def test_non_hebrew_sentences_skipped(self, db_engine, monkeypatch):
        from app.services import sentences_workspace_service as ws_module
        monkeypatch.setattr(
            ws_module.SentencesWorkspaceService,
            "get_sentence_texts_by_ids",
            lambda self, session, ids: {i: "hello world this is english" for i in ids},
        )

        svc = _make_svc()
        with Session(db_engine) as session:
            result = svc.run(
                session, [1, 2], lang="he", mode="fill_only",
                phonikud_generator=_FakeGenerator(),
            )
            session.commit()

        assert result.skipped_non_hebrew_ratio == 2
        assert result.inserted == 0

    def test_happy_path_fill_inserts(self, db_engine, monkeypatch):
        from app.services import sentences_workspace_service as ws_module
        monkeypatch.setattr(
            ws_module.SentencesWorkspaceService,
            "get_sentence_texts_by_ids",
            lambda self, session, ids: {i: f"בית הספר מספר {i}" for i in ids},
        )

        svc = _make_svc()
        with Session(db_engine) as session:
            result = svc.run(
                session, [1, 2, 3], lang="he", mode="fill_only",
                phonikud_generator=_FakeGenerator(),
            )
            session.commit()

        assert result.inserted == 3
        assert result.skipped_total == 0

    def test_override_rows_skipped(self, db_engine, monkeypatch):
        from app.services import sentences_workspace_service as ws_module
        monkeypatch.setattr(
            ws_module.SentencesWorkspaceService,
            "get_sentence_texts_by_ids",
            lambda self, session, ids: {i: f"בית הספר מספר {i}" for i in ids},
        )

        pron_svc = SentencePronunciationService()

        with Session(db_engine) as session:
            # Pre-seed sentence 1 as manual override
            pron_svc.upsert_manual(session, sentence_id=1, niqqud_text="שָׁלוֹם")
            session.commit()

            svc = _make_svc()
            result = svc.run(
                session, [1, 2, 3], lang="he", mode="fill_only",
                phonikud_generator=_FakeGenerator(),
            )
            session.commit()

        assert result.skipped_has_override == 1
        assert result.inserted == 2

    def test_same_hash_second_run_skipped(self, db_engine, monkeypatch):
        from app.services import sentences_workspace_service as ws_module
        texts = {i: f"בית הספר מספר {i}" for i in range(1, 4)}
        monkeypatch.setattr(
            ws_module.SentencesWorkspaceService,
            "get_sentence_texts_by_ids",
            lambda self, session, ids: {i: texts[i] for i in ids if i in texts},
        )

        svc = _make_svc()
        with Session(db_engine) as session:
            r1 = svc.run(session, [1, 2, 3], lang="he", mode="fill_only",
                         phonikud_generator=_FakeGenerator())
            session.commit()
            assert r1.inserted == 3

            r2 = svc.run(session, [1, 2, 3], lang="he", mode="fill_only",
                         phonikud_generator=_FakeGenerator())
            session.commit()

        assert r2.skipped_same_hash == 3
        assert r2.inserted == 0

    def test_generator_mode_updates_after_real_generation(self, db_engine, monkeypatch):
        from app.services import sentences_workspace_service as ws_module
        monkeypatch.setattr(
            SentencePronunciationService,
            "should_process",
            staticmethod(lambda text, *, guard=None: (True, "")),
        )
        monkeypatch.setattr(
            ws_module.SentencesWorkspaceService,
            "get_sentence_texts_by_ids",
            lambda self, session, ids: {i: f"Ч‘Ч™ЧЄ Ч”ЧЎЧ¤ЧЁ ЧћЧЎЧ¤ЧЁ {i}" for i in ids},
        )

        svc = _make_svc()
        generator = _ModeSwitchingGenerator()
        with Session(db_engine) as session:
            result = svc.run(
                session,
                [1],
                lang="he",
                mode="fill_only",
                phonikud_generator=generator,
            )
            session.commit()
            row = session.get(SentencePronunciation, 1)

        assert result.generator_mode == "real"
        assert row is not None
        assert row.phonikud_version == "real"
