"""Bootstrap must infer pronunciation from source text while keeping canonical key."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.domain.normalization.normalizer import normalize_for_tm
from app.infra.sa_models import Lemma, PronunciationEntry
from app.services.pronunciation_bootstrap_service import PronunciationBootstrapService, PronunciationGenerator


def _workspace_temp_dir(prefix: str) -> Path:
    root = Path("build") / "tmp_tests"
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=str(root)))


class _CaptureGenerator(PronunciationGenerator):
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def generate(self, lang: str, source_texts: list[str]):
        _ = lang
        self.calls.append(list(source_texts))
        result = {}
        for text in source_texts:
            # Intentional separators to verify sanitizer in bootstrap path.
            result[text] = {
                "niqqud_text": text.replace(" ", "_") + "|auto",
                "ipa": None,
                "reading_text": None,
                "confidence": 0.7,
                "notes": "auto:fake",
            }
        return result


def test_bootstrap_uses_surface_text_and_sanitizes_generated_value():
    temp_dir = _workspace_temp_dir("pron_bootstrap_surface_")
    engine = create_engine(f"sqlite:///{temp_dir / 'pron.db'}")
    try:
        Lemma.__table__.create(engine, checkfirst=True)
        PronunciationEntry.__table__.create(engine, checkfirst=True)
        generator = _CaptureGenerator()
        service = PronunciationBootstrapService(generator=generator)

        source_text = "התחנה הבאה"
        source_norm = normalize_for_tm("he", source_text, "lemma").norm

        with Session(engine) as session:
            session.add(
                Lemma(
                    project_id=1,
                    lemma_text=source_text,
                    pos="NOUN",
                    norm_text=source_norm,
                )
            )
            session.commit()

            result = service.bootstrap(
                session,
                lang="he",
                chunk_size=50,
                include_lemmas=True,
                include_terms=False,
                include_user_dictionary=False,
            )
            session.commit()

            assert result.updated == 1
            assert generator.calls, "Generator must be invoked"
            assert source_text in generator.calls[0]

            row = session.query(PronunciationEntry).filter_by(lang="he", src_norm=source_norm).one()
            assert row.source == "auto_phonikud"
            assert row.niqqud_text is not None
            assert "_" not in row.niqqud_text
            assert "|" not in row.niqqud_text
    finally:
        engine.dispose()
        shutil.rmtree(temp_dir, ignore_errors=True)
