"""Tests for pronunciation import/export policy service."""

from __future__ import annotations

import csv
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


def test_pronunciation_import_export_roundtrip():
    temp_dir = _workspace_temp_dir("pron_xchg_")
    engine = create_engine(f"sqlite:///{temp_dir / 'pron.db'}")
    try:
        PronunciationEntry.__table__.create(engine, checkfirst=True)
        svc = PronunciationImportExportService()
        in_path = temp_dir / "in.tsv"
        out_path = temp_dir / "out.tsv"

        with in_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, delimiter="\t")
            writer.writerow(
                ["lang", "src_norm", "niqqud_text", "ipa", "source", "is_override", "notes"]
            )
            writer.writerow(["he", "shalom", "שָׁלוֹם", "", "manual", "1", "seed"])
            writer.writerow(["he", "bayit", "בַּיִת", "", "auto", "0", "seed"])

        with Session(engine) as session:
            result = svc.import_file(session, in_path=in_path, delimiter="\t")
            session.commit()
            assert result["processed"] == 2
            assert result["updated"] == 2

            exported = svc.export_file(session, out_path=out_path, delimiter="\t")
            assert exported["exported"] == 2

        lines = out_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 3
        assert lines[0].startswith("lang\t")
    finally:
        engine.dispose()
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_pronunciation_import_keeps_manual_override():
    temp_dir = _workspace_temp_dir("pron_xchg_manual_")
    engine = create_engine(f"sqlite:///{temp_dir / 'pron.db'}")
    try:
        PronunciationEntry.__table__.create(engine, checkfirst=True)
        imp = PronunciationImportExportService()
        base = PronunciationService()
        in_path = temp_dir / "in.tsv"

        with Session(engine) as session:
            base.upsert_entry(
                session,
                lang="he",
                src_norm="shalom",
                niqqud_text="MANUAL",
                ipa=None,
                source="manual",
                is_override=True,
                notes="locked",
            )
            session.commit()

        with in_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, delimiter="\t")
            writer.writerow(
                ["lang", "src_norm", "niqqud_text", "ipa", "source", "is_override", "notes"]
            )
            writer.writerow(["he", "shalom", "AUTO", "", "auto", "0", "auto"])

        with Session(engine) as session:
            imp.import_file(session, in_path=in_path, delimiter="\t", allow_auto_overwrite=True)
            session.commit()
            row = base.get_entry(session, lang="he", src_norm="shalom")
            assert row is not None
            assert row.source == "manual"
            assert row.niqqud_text == "MANUAL"
    finally:
        engine.dispose()
        shutil.rmtree(temp_dir, ignore_errors=True)
