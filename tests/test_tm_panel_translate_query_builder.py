"""Tests for TM all-filtered ID selection used by batch translate."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.infra.sa_models import DictProject, Library, TMEntry
from app.services.translation_admin_service import TranslationAdminService


@pytest.fixture
def tm_filters_db():
    """SQLite DB with TM rows for filter/query builder tests."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        Library.__table__.create(engine, checkfirst=True)
        DictProject.__table__.create(engine, checkfirst=True)
        TMEntry.__table__.create(engine, checkfirst=True)

        with Session(engine) as session:
            lib = Library(name="L")
            session.add(lib)
            session.flush()
            p1 = DictProject(library_id=lib.library_id, name="P1")
            p2 = DictProject(library_id=lib.library_id, name="P2")
            session.add_all([p1, p2])
            session.flush()

            rows = [
                # Included for P1/global + approved + lemma
                TMEntry(project_id=p1.project_id, kind="lemma", src_lang="he", tgt_lang="ru", src_text="a", src_norm="a", translation="", status="approved", origin="import", is_noise=0),
                TMEntry(project_id=p1.project_id, kind="lemma", src_lang="he", tgt_lang="ru", src_text="b", src_norm="b", translation="filled", status="approved", origin="import", is_noise=0),
                TMEntry(project_id=None, kind="lemma", src_lang="he", tgt_lang="ru", src_text="c", src_norm="c", translation="", status="approved", origin="import", is_noise=0),
                # Excluded by filters
                TMEntry(project_id=p2.project_id, kind="lemma", src_lang="he", tgt_lang="ru", src_text="d", src_norm="d", translation="", status="approved", origin="import", is_noise=0),
                TMEntry(project_id=p1.project_id, kind="term_cluster", src_lang="he", tgt_lang="ru", src_text="e", src_norm="e", translation="", status="approved", origin="import", is_noise=0),
                TMEntry(project_id=p1.project_id, kind="lemma", src_lang="he", tgt_lang="ru", src_text="f", src_norm="f", translation="", status="rejected", origin="import", is_noise=0),
                TMEntry(project_id=p1.project_id, kind="lemma", src_lang="he", tgt_lang="ru", src_text="g", src_norm="g", translation="", status="approved", origin="import", is_noise=1),
            ]
            session.add_all(rows)
            session.commit()
            yield engine, p1.project_id
    finally:
        engine.dispose()
        Path(db_path).unlink(missing_ok=True)


def test_build_filtered_tm_ids_respects_filters(tm_filters_db):
    """Count/fetch should apply TM filters and write-mode semantics."""
    engine, p1_id = tm_filters_db
    service = TranslationAdminService()
    filters = {
        "kind": "lemma",
        "status": "approved",
        "project_ids": [p1_id, -1],
        "hide_noise": True,
    }

    with Session(engine) as session:
        overwrite_ids = service.fetch_tm_ids_for_translation(session, filters, "OVERWRITE", limit=100, offset=0)
        fill_empty_ids = service.fetch_tm_ids_for_translation(session, filters, "FILL_EMPTY", limit=100, offset=0)
        fill_empty_count = service.count_tm_ids_for_translation(session, filters, "FILL_EMPTY")

    assert len(overwrite_ids) == 3
    assert len(fill_empty_ids) == 2
    assert fill_empty_count == 2
    assert overwrite_ids == sorted(overwrite_ids)
    assert fill_empty_ids == sorted(fill_empty_ids)


def test_build_filtered_tm_ids_respects_hide_noise(tm_filters_db):
    """hide_noise=True should exclude rows with is_noise=1."""
    engine, p1_id = tm_filters_db
    service = TranslationAdminService()
    base_filters = {
        "kind": "lemma",
        "status": "approved",
        "project_ids": [p1_id, -1],
    }

    with Session(engine) as session:
        ids_with_noise = service.fetch_tm_ids_for_translation(
            session,
            {**base_filters, "hide_noise": False},
            "OVERWRITE",
            limit=100,
            offset=0,
        )
        ids_without_noise = service.fetch_tm_ids_for_translation(
            session,
            {**base_filters, "hide_noise": True},
            "OVERWRITE",
            limit=100,
            offset=0,
        )

    assert len(ids_with_noise) == len(ids_without_noise) + 1


def test_chunking_behavior(tm_filters_db):
    """ID fetch should support deterministic limit/offset chunking."""
    engine, _ = tm_filters_db
    service = TranslationAdminService()

    with Session(engine) as session:
        full = service.fetch_tm_ids_for_translation(
            session,
            {"hide_noise": False},
            "OVERWRITE",
            limit=100,
            offset=0,
        )
        chunk_1 = service.fetch_tm_ids_for_translation(
            session,
            {"hide_noise": False},
            "OVERWRITE",
            limit=2,
            offset=0,
        )
        chunk_2 = service.fetch_tm_ids_for_translation(
            session,
            {"hide_noise": False},
            "OVERWRITE",
            limit=2,
            offset=2,
        )
        chunk_3 = service.fetch_tm_ids_for_translation(
            session,
            {"hide_noise": False},
            "OVERWRITE",
            limit=2,
            offset=4,
        )
        chunk_4 = service.fetch_tm_ids_for_translation(
            session,
            {"hide_noise": False},
            "OVERWRITE",
            limit=2,
            offset=6,
        )

    assert full == sorted(full)
    assert full == chunk_1 + chunk_2 + chunk_3 + chunk_4
