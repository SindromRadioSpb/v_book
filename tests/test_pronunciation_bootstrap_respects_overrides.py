"""Regression: bootstrap must not overwrite manual pronunciation overrides."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.infra.sa_models import PronunciationEntry
from app.services.pronunciation_bootstrap_service import (
    PronunciationBootstrapService,
    PronunciationGenerator,
)
from app.services.pronunciation_service import PronunciationService


def _workspace_temp_dir(prefix: str) -> Path:
    root = Path("build") / "tmp_tests"
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=str(root)))


class _FakeGenerator(PronunciationGenerator):
    def generate(self, lang: str, src_norms: list[str]):
        _ = lang
        return {
            norm: {"niqqud_text": f"{norm}_auto", "ipa": None, "notes": "fake"}
            for norm in src_norms
        }


def test_bootstrap_respects_manual_override_even_in_rebuild_mode(monkeypatch):
    temp_dir = _workspace_temp_dir("pron_bootstrap_override_")
    engine = create_engine(f"sqlite:///{temp_dir / 'pron.db'}")
    try:
        PronunciationEntry.__table__.create(engine, checkfirst=True)
        bootstrap = PronunciationBootstrapService(generator=_FakeGenerator())
        service = PronunciationService()
        monkeypatch.setattr(bootstrap, "collect_unique_src_norms", lambda *a, **k: ["שלום"])

        with Session(engine) as session:
            service.upsert_entry(
                session,
                lang="he",
                src_norm="שלום",
                niqqud_text="שָׁלוֹם",
                ipa=None,
                source="manual",
                is_override=True,
                notes="manual keep",
            )
            session.commit()

            result = bootstrap.bootstrap(session, lang="he", chunk_size=100, rebuild_auto=True)
            session.commit()

            row = service.get_entry(session, lang="he", src_norm="שלום")
            assert row is not None
            assert row.source == "manual"
            assert row.niqqud_text == "שָׁלוֹם"
            assert result.updated == 0
    finally:
        engine.dispose()
        shutil.rmtree(temp_dir, ignore_errors=True)
