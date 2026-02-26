"""Tests for full lemma->tm_entry materialization in project scope."""

from __future__ import annotations

import tempfile
from pathlib import Path

from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

from app.infra.sa_models import Library, DictProject, Lemma, TMEntry
from app.services.translation_admin_service import TranslationAdminService


def _make_engine():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_engine(f"sqlite:///{tmp.name}")
    return engine, Path(tmp.name)


def _setup_schema(engine):
    Library.__table__.create(engine, checkfirst=True)
    DictProject.__table__.create(engine, checkfirst=True)
    Lemma.__table__.create(engine, checkfirst=True)
    TMEntry.__table__.create(engine, checkfirst=True)


def _seed_project(session: Session, *, lemmas: int = 5) -> int:
    library = Library(name="L")
    session.add(library)
    session.flush()
    project = DictProject(library_id=library.library_id, name="P", src_lang="he", tgt_lang="ru")
    session.add(project)
    session.flush()

    for i in range(lemmas):
        session.add(
            Lemma(
                project_id=project.project_id,
                lemma_text=f"lemma_{i}",
                pos="NOUN",
                is_noise=0,
            )
        )
    session.flush()
    session.commit()
    return int(project.project_id)


def test_materialize_project_lemmas_to_tm_creates_missing_rows():
    engine, db_path = _make_engine()
    try:
        _setup_schema(engine)
        service = TranslationAdminService()
        with Session(engine) as session:
            project_id = _seed_project(session, lemmas=5)
            first_lemma = session.execute(
                select(Lemma).where(Lemma.project_id == project_id).order_by(Lemma.lemma_id.asc()).limit(1)
            ).scalar_one()
            session.add(
                TMEntry(
                    project_id=project_id,
                    kind="lemma",
                    src_lang="he",
                    tgt_lang="ru",
                    src_text=first_lemma.lemma_text,
                    src_norm=first_lemma.lemma_text,
                    translation="",
                    status="draft",
                    origin="import",
                    source_ref="seed",
                    lemma_id=first_lemma.lemma_id,
                    is_noise=0,
                )
            )
            session.commit()

            stats = service.materialize_project_lemmas_to_tm(session, project_id, chunk_size=2)

            assert stats["initial_missing_lemma_links"] == 4
            assert stats["inserted"] == 4
            assert stats["final_missing_lemma_links"] == 0
            assert stats["final_tm_lemmas"] == 5

            created_count = session.execute(
                select(func.count())
                .select_from(TMEntry)
                .where(TMEntry.project_id == project_id, TMEntry.kind == "lemma", TMEntry.source_ref == "lemma_materialize_full")
            ).scalar()
            assert int(created_count or 0) == 4
    finally:
        engine.dispose()
        db_path.unlink(missing_ok=True)


def test_materialize_project_lemmas_to_tm_is_idempotent():
    engine, db_path = _make_engine()
    try:
        _setup_schema(engine)
        service = TranslationAdminService()
        with Session(engine) as session:
            project_id = _seed_project(session, lemmas=4)
            first = service.materialize_project_lemmas_to_tm(session, project_id, chunk_size=2)
            second = service.materialize_project_lemmas_to_tm(session, project_id, chunk_size=2)

            assert first["inserted"] == 4
            assert first["final_missing_lemma_links"] == 0
            assert second["initial_missing_lemma_links"] == 0
            assert second["inserted"] == 0
            assert second["final_missing_lemma_links"] == 0
    finally:
        engine.dispose()
        db_path.unlink(missing_ok=True)


def test_materialize_project_lemmas_to_tm_dry_run_does_not_write():
    engine, db_path = _make_engine()
    try:
        _setup_schema(engine)
        service = TranslationAdminService()
        with Session(engine) as session:
            project_id = _seed_project(session, lemmas=3)
            stats = service.materialize_project_lemmas_to_tm(session, project_id, dry_run=True)
            tm_count = session.execute(
                select(func.count()).select_from(TMEntry).where(TMEntry.project_id == project_id, TMEntry.kind == "lemma")
            ).scalar()

            assert stats["initial_missing_lemma_links"] == 3
            assert stats["inserted"] == 0
            assert int(tm_count or 0) == 0
    finally:
        engine.dispose()
        db_path.unlink(missing_ok=True)

