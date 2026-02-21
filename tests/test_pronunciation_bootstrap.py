"""Pronunciation bootstrap service tests."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.domain.normalization.normalizer import normalize_for_tm
from app.infra.sa_models import PronunciationEntry
from app.services.pronunciation_bootstrap_service import PronunciationBootstrapService, PronunciationGenerator
from app.services.pronunciation_service import PronunciationService


def _workspace_temp_dir(prefix: str) -> Path:
    root = Path("build") / "tmp_tests"
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=str(root)))


class _FakeGenerator(PronunciationGenerator):
    def generate(self, lang: str, src_norms: list[str]):
        _ = lang
        return {norm: {"niqqud_text": f"{norm}_nikud", "ipa": None, "notes": "fake"} for norm in src_norms}


class _MismatchGenerator(PronunciationGenerator):
    def generate(self, lang: str, source_texts: list[str]):
        _ = lang
        return {
            text: {
                "niqqud_text": ("\u05e4\u05e8\u05e7 \u05d6\u05de\u05df" if text == "\u05e4\u05e8\u05e7 \u05d4\u05d6\u05de\u05df" else text),
                "ipa": None,
                "notes": "fake_mismatch",
            }
            for text in source_texts
        }


def test_bootstrap_is_idempotent_on_second_run(monkeypatch):
    temp_dir = _workspace_temp_dir("pron_bootstrap_")
    engine = create_engine(f"sqlite:///{temp_dir / 'pron.db'}")
    try:
        PronunciationEntry.__table__.create(engine, checkfirst=True)
        service = PronunciationBootstrapService(generator=_FakeGenerator())
        monkeypatch.setattr(service, "collect_unique_src_norms", lambda *a, **k: ["a", "b", "c"])

        with Session(engine) as session:
            first = service.bootstrap(session, lang="he", chunk_size=2, rebuild_auto=False)
            session.commit()
            second = service.bootstrap(session, lang="he", chunk_size=2, rebuild_auto=False)
            session.commit()

            assert first.updated == 3
            assert second.updated == 0
            assert first.failed == 0 and second.failed == 0
    finally:
        engine.dispose()
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_bootstrap_does_not_override_manual(monkeypatch):
    temp_dir = _workspace_temp_dir("pron_bootstrap_manual_")
    engine = create_engine(f"sqlite:///{temp_dir / 'pron.db'}")
    try:
        PronunciationEntry.__table__.create(engine, checkfirst=True)
        bootstrap = PronunciationBootstrapService(generator=_FakeGenerator())
        pron = PronunciationService()
        monkeypatch.setattr(bootstrap, "collect_unique_src_norms", lambda *a, **k: ["a"])

        with Session(engine) as session:
            pron.upsert_entry(
                session,
                lang="he",
                src_norm="a",
                niqqud_text="manual_value",
                ipa=None,
                source="manual",
                is_override=True,
                notes="manual",
            )
            session.commit()

            bootstrap.bootstrap(session, lang="he", chunk_size=1, rebuild_auto=True)
            session.commit()

            row = pron.get_entry(session, lang="he", src_norm="a")
            assert row is not None
            assert row.source == "manual"
            assert row.niqqud_text == "manual value"
    finally:
        engine.dispose()
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_bootstrap_selected_items_respects_source_group_filters():
    temp_dir = _workspace_temp_dir("pron_bootstrap_selected_")
    engine = create_engine(f"sqlite:///{temp_dir / 'pron.db'}")
    try:
        PronunciationEntry.__table__.create(engine, checkfirst=True)
        service = PronunciationBootstrapService(generator=_FakeGenerator())

        with Session(engine) as session:
            result = service.bootstrap(
                session,
                lang="he",
                chunk_size=10,
                include_lemmas=True,
                include_terms=False,
                include_user_dictionary=False,
                selected_items=[
                    {"src_lang": "he", "src_norm": "lemma_norm", "src_text": "lemma text", "source_group": "lemmas"},
                    {"src_lang": "he", "src_norm": "term_norm", "src_text": "term text", "source_group": "terms"},
                ],
            )
            session.commit()

            assert result.total_candidates == 1
            assert result.updated == 1

            rows = session.query(PronunciationEntry).all()
            assert len(rows) == 1
            assert rows[0].src_norm == normalize_for_tm("he", "lemma text", "surface").norm
    finally:
        engine.dispose()
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_bootstrap_selected_items_uses_surface_norm_for_lemmas_and_terms():
    temp_dir = _workspace_temp_dir("pron_bootstrap_selected_surface_")
    engine = create_engine(f"sqlite:///{temp_dir / 'pron.db'}")
    try:
        PronunciationEntry.__table__.create(engine, checkfirst=True)
        service = PronunciationBootstrapService(generator=_FakeGenerator())

        with Session(engine) as session:
            result = service.bootstrap(
                session,
                lang="he",
                chunk_size=10,
                include_lemmas=True,
                include_terms=True,
                include_user_dictionary=False,
                selected_items=[
                    {"src_lang": "he", "src_norm": "same_norm", "src_text": "alpha", "source_group": "lemmas"},
                    {"src_lang": "he", "src_norm": "same_norm", "src_text": "beta", "source_group": "terms"},
                ],
            )
            session.commit()

            assert result.total_candidates == 2
            assert result.updated == 2

            rows = session.query(PronunciationEntry).all()
            norms = sorted(row.src_norm for row in rows)
            assert norms == sorted(
                [
                    normalize_for_tm("he", "alpha", "surface").norm,
                    normalize_for_tm("he", "beta", "surface").norm,
                ]
            )
    finally:
        engine.dispose()
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_bootstrap_selected_lemma_prefix_forms_do_not_collapse_to_one_candidate():
    temp_dir = _workspace_temp_dir("pron_bootstrap_selected_prefixes_")
    engine = create_engine(f"sqlite:///{temp_dir / 'pron.db'}")
    try:
        PronunciationEntry.__table__.create(engine, checkfirst=True)
        service = PronunciationBootstrapService(generator=_FakeGenerator())
        selected = [
            {"src_lang": "he", "src_norm": "פלדה", "src_text": "בפלדה", "source_group": "lemmas"},
            {"src_lang": "he", "src_norm": "פלדה", "src_text": "לפלדה", "source_group": "lemmas"},
            {"src_lang": "he", "src_norm": "פלדה", "src_text": "מפלדה", "source_group": "lemmas"},
            {"src_lang": "he", "src_norm": "פלדה", "src_text": "הפלדה", "source_group": "lemmas"},
            {"src_lang": "he", "src_norm": "פלדה", "src_text": "פלדה", "source_group": "lemmas"},
        ]

        with Session(engine) as session:
            result = service.bootstrap(
                session,
                lang="he",
                chunk_size=10,
                include_lemmas=True,
                include_terms=False,
                include_user_dictionary=False,
                selected_items=selected,
            )
            session.commit()

            assert result.total_candidates == 5
            assert result.updated == 5
            rows = session.query(PronunciationEntry).all()
            assert len(rows) == 5
    finally:
        engine.dispose()
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_bootstrap_falls_back_to_source_when_generated_structure_mismatch():
    temp_dir = _workspace_temp_dir("pron_bootstrap_structure_fallback_")
    engine = create_engine(f"sqlite:///{temp_dir / 'pron.db'}")
    try:
        PronunciationEntry.__table__.create(engine, checkfirst=True)
        service = PronunciationBootstrapService(generator=_MismatchGenerator())

        selected = [
            {"src_lang": "he", "src_norm": "shared_norm", "src_text": "\u05e4\u05e8\u05e7 \u05d4\u05d6\u05de\u05df", "source_group": "terms"},
            {"src_lang": "he", "src_norm": "shared_norm", "src_text": "\u05e4\u05e8\u05e7 \u05d6\u05de\u05df", "source_group": "terms"},
        ]

        with Session(engine) as session:
            result = service.bootstrap(
                session,
                lang="he",
                chunk_size=10,
                include_lemmas=False,
                include_terms=True,
                include_user_dictionary=False,
                selected_items=selected,
            )
            session.commit()

            assert result.total_candidates == 2
            rows = session.query(PronunciationEntry).all()
            by_norm = {row.src_norm: row for row in rows}
            first_norm = normalize_for_tm("he", "\u05e4\u05e8\u05e7 \u05d4\u05d6\u05de\u05df", "surface").norm
            second_norm = normalize_for_tm("he", "\u05e4\u05e8\u05e7 \u05d6\u05de\u05df", "surface").norm
            assert by_norm[first_norm].niqqud_text == "\u05e4\u05e8\u05e7 \u05d4\u05d6\u05de\u05df"
            assert "qc:source_structure_fallback" in (by_norm[first_norm].notes or "")
            assert by_norm[second_norm].niqqud_text == "\u05e4\u05e8\u05e7 \u05d6\u05de\u05df"
    finally:
        engine.dispose()
        shutil.rmtree(temp_dir, ignore_errors=True)
