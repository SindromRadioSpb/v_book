"""PLS import/export tests for pronunciation metadata."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.infra.sa_models import PronunciationEntry
from app.services.pronunciation_import_export_service import PronunciationImportExportService
from app.services.pronunciation_service import PronunciationService


def _workspace_temp_dir(prefix: str) -> Path:
    root = Path("build") / "tmp_tests"
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=str(root)))


def test_pls_export_import_roundtrip():
    temp_dir = _workspace_temp_dir("pron_pls_")
    engine = create_engine(f"sqlite:///{temp_dir / 'pron.db'}")
    try:
        PronunciationEntry.__table__.create(engine, checkfirst=True)
        svc = PronunciationService()
        exchange = PronunciationImportExportService(service=svc)
        pls_path = temp_dir / "he.pls"

        with Session(engine) as session:
            svc.upsert_entry(
                session,
                lang="he",
                src_norm="shalom",
                niqqud_text=None,
                ipa="ʃaˈlom",
                source="manual",
                is_override=True,
                confidence=1.0,
            )
            session.commit()
            exported = exchange.export_pls(session, out_path=pls_path, lang="he")
            assert exported["exported"] == 1

        # Clear and import back as non-override metadata.
        with Session(engine) as session:
            session.query(PronunciationEntry).delete()
            session.commit()
            imported = exchange.import_pls(
                session, in_path=pls_path, default_lang="he", is_override=False
            )
            session.commit()
            assert imported["processed"] >= 1
            assert imported["updated"] == 1
            row = svc.get_entry(session, lang="he", src_norm="shalom")
            assert row is not None
            assert row.ipa == "ʃaˈlom"
            assert row.source == "import_pls"
            assert row.is_override == 0
    finally:
        engine.dispose()
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_pls_import_does_not_override_manual():
    temp_dir = _workspace_temp_dir("pron_pls_manual_")
    engine = create_engine(f"sqlite:///{temp_dir / 'pron.db'}")
    try:
        PronunciationEntry.__table__.create(engine, checkfirst=True)
        svc = PronunciationService()
        exchange = PronunciationImportExportService(service=svc)
        pls_path = temp_dir / "he.pls"

        with Session(engine) as session:
            svc.upsert_entry(
                session,
                lang="he",
                src_norm="bayit",
                niqqud_text="בַּיִת",
                ipa=None,
                source="manual",
                is_override=True,
                notes="locked",
            )
            svc.upsert_entry(
                session,
                lang="he",
                src_norm="foo",
                niqqud_text=None,
                ipa="fu",
                source="manual",
                is_override=True,
            )
            session.commit()
            exchange.export_pls(session, out_path=pls_path, lang="he")

        with Session(engine) as session:
            imported = exchange.import_pls(
                session, in_path=pls_path, default_lang="he", is_override=False
            )
            session.commit()
            assert imported["processed"] >= 1
            row = svc.get_entry(session, lang="he", src_norm="foo")
            assert row is not None
            assert row.source == "manual"
            assert row.ipa == "fu"
    finally:
        engine.dispose()
        shutil.rmtree(temp_dir, ignore_errors=True)
