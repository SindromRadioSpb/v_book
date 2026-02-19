"""Pronunciation service merge-policy tests."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.infra.sa_models import PronunciationEntry
from app.services.pronunciation_service import PronunciationService


def _workspace_temp_dir(prefix: str) -> Path:
    root = Path("build") / "tmp_tests"
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=str(root)))


def test_manual_override_wins_over_auto():
    temp_dir = _workspace_temp_dir("pron_merge_")
    engine = create_engine(f"sqlite:///{temp_dir / 'pron.db'}")
    try:
        PronunciationEntry.__table__.create(engine, checkfirst=True)
        service = PronunciationService()
        with Session(engine) as session:
            service.upsert_entry(
                session,
                lang="he",
                src_norm="shalom",
                niqqud_text="שָׁלוֹם",
                ipa=None,
                source="manual",
                is_override=True,
                notes="manual",
            )
            session.commit()

            service.upsert_entry(
                session,
                lang="he",
                src_norm="shalom",
                niqqud_text="AUTO_VALUE",
                ipa=None,
                source="auto",
                is_override=False,
                notes="auto",
                allow_auto_overwrite=True,
            )
            session.commit()

            row = service.get_entry(session, lang="he", src_norm="shalom")
            assert row is not None
            assert row.source == "manual"
            assert row.is_override == 1
            assert row.niqqud_text == "שָׁלוֹם"
    finally:
        engine.dispose()
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_bulk_upsert_auto_is_idempotent():
    temp_dir = _workspace_temp_dir("pron_idem_")
    engine = create_engine(f"sqlite:///{temp_dir / 'pron.db'}")
    try:
        PronunciationEntry.__table__.create(engine, checkfirst=True)
        service = PronunciationService()
        payload = [
            {"src_norm": "shalom", "niqqud_text": "שָׁלוֹם"},
            {"src_norm": "bayit", "niqqud_text": "בַּיִת"},
        ]
        with Session(engine) as session:
            first = service.bulk_upsert_auto(session, lang="he", entries=payload, chunk_size=1)
            session.commit()
            second = service.bulk_upsert_auto(session, lang="he", entries=payload, chunk_size=1)
            session.commit()

            assert first["updated"] == 2
            assert second["updated"] == 0
            assert second["skipped"] == 2
    finally:
        engine.dispose()
        shutil.rmtree(temp_dir, ignore_errors=True)
