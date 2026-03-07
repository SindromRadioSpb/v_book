"""Regression tests for project/corpus ID allocation under orphaned rows."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from app.infra.sa_models import Library, SourceCorpus, SourceDocument
from app.services.project_service import ProjectService


def _apply_migrations(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        for sql_file in sorted(Path("app/infra/migrations").glob("*.sql")):
            conn.executescript(sql_file.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


def _seed_base_data(db_path: Path, *, with_orphans: bool) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys=OFF")
        cur.execute("INSERT INTO library(library_id, name) VALUES (1, 'Default Library')")
        cur.execute(
            "INSERT INTO dict_project(project_id, library_id, name) "
            "VALUES (1, 1, 'Reference')"
        )
        cur.execute(
            "INSERT INTO source_corpus(corpus_id, project_id, name) "
            "VALUES (1, 1, 'Main Corpus')"
        )
        if with_orphans:
            # Simulate leftover rows from a corrupted delete path.
            cur.execute(
                "INSERT INTO lemma(lemma_id, project_id, lemma_text) "
                "VALUES (1, 2, 'orphan_lemma')"
            )
            cur.execute(
                "INSERT INTO source_document("
                "  doc_id, corpus_id, file_path, file_name, file_ext, sha256"
                ") VALUES (1, 2, 'C:/tmp/orphan.txt', 'orphan.txt', '.txt', 'orphan_sha')"
            )
        conn.commit()
    finally:
        conn.close()


def _make_session(db_path: Path):
    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_pragma(conn, _rec):
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    return engine, Session()


def _make_service() -> ProjectService:
    service = ProjectService.__new__(ProjectService)
    service.db_service = None
    return service


def test_create_project_allocates_next_ids_without_orphans():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)
    try:
        _apply_migrations(db_path)
        _seed_base_data(db_path, with_orphans=False)
        engine, session = _make_session(db_path)
        try:
            lib = session.execute(
                select(Library).where(Library.library_id == 1)
            ).scalar_one()
            project = _make_service().create_project(
                session,
                name="Regular project",
                library=lib,
                auto_assign_reference=False,
            )
            corpus = session.execute(
                select(SourceCorpus).where(SourceCorpus.project_id == project.project_id)
            ).scalar_one()

            assert project.project_id == 2
            assert corpus.corpus_id == 2
        finally:
            session.close()
            engine.dispose()
    finally:
        db_path.unlink(missing_ok=True)


def test_create_project_avoids_reusing_ids_when_orphans_exist():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)
    try:
        _apply_migrations(db_path)
        _seed_base_data(db_path, with_orphans=True)
        engine, session = _make_session(db_path)
        try:
            lib = session.execute(
                select(Library).where(Library.library_id == 1)
            ).scalar_one()
            project = _make_service().create_project(
                session,
                name="Recovered project",
                library=lib,
                auto_assign_reference=False,
            )
            corpus = session.execute(
                select(SourceCorpus).where(SourceCorpus.project_id == project.project_id)
            ).scalar_one()
            docs_count = session.execute(
                select(func.count())
                .select_from(SourceDocument)
                .join(SourceCorpus, SourceDocument.corpus_id == SourceCorpus.corpus_id)
                .where(SourceCorpus.project_id == project.project_id)
            ).scalar_one()

            assert project.project_id == 3
            assert corpus.corpus_id == 3
            assert docs_count == 0
        finally:
            session.close()
            engine.dispose()
    finally:
        db_path.unlink(missing_ok=True)

