"""Bootstrap must infer pronunciation from source text while keeping canonical key."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.domain.normalization.normalizer import normalize_for_tm
from app.infra.sa_models import PronunciationEntry
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
            # Replace spaces with "_|" so the sanitizer converts both _ and | back to
            # spaces — this verifies separator stripping without adding extra words.
            # Hebrew PATAH (U+05B7) appended to the final char so has_hebrew_nikud()
            # accepts the value AND the letter signature still matches the source.
            result[text] = {
                "niqqud_text": text.replace(" ", "_|") + "\u05B7",
                "ipa": None,
                "reading_text": None,
                "confidence": 0.7,
                "notes": "auto:fake",
            }
        return result


def test_bootstrap_uses_surface_text_and_sanitizes_generated_value():
    """Bootstrap passes surface text to generator and sanitizes separators in stored niqqud.

    Uses selected_items to supply the source text directly, avoiding any DB schema
    dependencies (no Lemma/DictProject tables needed in the slim test engine).
    """
    temp_dir = _workspace_temp_dir("pron_bootstrap_surface_")
    engine = create_engine(f"sqlite:///{temp_dir / 'pron.db'}")
    try:
        PronunciationEntry.__table__.create(engine, checkfirst=True)
        generator = _CaptureGenerator()
        service = PronunciationBootstrapService(generator=generator)

        source_text = "התחנה הבאה"
        src_lang = "he"
        surface_norm = normalize_for_tm(src_lang, source_text, "surface").norm

        with Session(engine) as session:
            result = service.bootstrap(
                session,
                lang=src_lang,
                chunk_size=50,
                include_lemmas=True,
                include_terms=False,
                include_user_dictionary=False,
                selected_items=[
                    {
                        "src_lang": src_lang,
                        "src_norm": surface_norm,
                        "src_text": source_text,
                        "source_group": "lemmas",
                    }
                ],
            )
            session.commit()

            assert result.updated == 1
            assert generator.calls, "Generator must be invoked"
            assert source_text in generator.calls[0]

            row = session.query(PronunciationEntry).filter_by(lang=src_lang, src_norm=surface_norm).one()
            assert row.source == "auto_phonikud"
            assert row.niqqud_text is not None
            assert "_" not in row.niqqud_text
            assert "|" not in row.niqqud_text
    finally:
        engine.dispose()
        shutil.rmtree(temp_dir, ignore_errors=True)
