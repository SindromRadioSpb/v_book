"""Integration tests for fast project deletion (explicit delete, bypass FK cascade).

Root cause: lemma_doc_stat has no lemma_id index — FK cascade from lemma deletion
causes O(104M) full table scans per lemma even for tiny projects.

Fix: PRAGMA foreign_keys=OFF + explicit child-table deletes by project_id.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from app.infra.sa_models import (
    DictProject, Library, SourceCorpus, SourceDocument, DocumentSentence, Lemma,
)
from app.services.project_service import ProjectService


def _make_engine(db_path: Path):
    engine = create_engine(f"sqlite:///{db_path}", echo=False,
                           connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def set_pragma(conn, _rec):
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

    # Mirror DatabaseManager: restore foreign_keys=ON on every pool checkout
    # (guards against PRAGMA foreign_keys=OFF left by delete_project).
    @event.listens_for(engine, "checkout")
    def reset_fk_on_checkout(dbapi_conn, _rec, _proxy):
        try:
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
        except Exception:
            pass

    return engine


def _apply_migrations(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        for sql_file in sorted(Path("app/infra/migrations").glob("*.sql")):
            conn.executescript(sql_file.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


def _make_test_db():
    """Return (db_path, session, project_id, engine). Caller must clean up."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    _apply_migrations(db_path)
    engine = _make_engine(db_path)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()

    lib = Library(name="TestLib")
    session.add(lib)
    session.flush()

    proj = DictProject(library_id=lib.library_id, name="DeleteMe",
                       description="test", src_lang="he", tgt_lang="ru")
    session.add(proj)
    session.flush()

    corpus = SourceCorpus(project_id=proj.project_id, name="Main", description="")
    session.add(corpus)
    session.flush()

    doc = SourceDocument(
        corpus_id=corpus.corpus_id,
        file_path="/tmp/x.txt", file_name="x.txt", file_ext=".txt",
        sha256="abc123", sentence_count=3,
    )
    session.add(doc)
    session.flush()

    for i in range(3):
        session.add(DocumentSentence(doc_id=doc.doc_id, sent_index=i, text=f"מילה {i}"))

    for i in range(5):
        session.add(Lemma(project_id=proj.project_id, lemma_text=f"lemma_{i}", pos="NOUN"))

    session.commit()
    return db_path, session, proj.project_id, engine


def test_delete_project_removes_all_data():
    db_path, session, project_id, engine = _make_test_db()
    try:
        svc = ProjectService.__new__(ProjectService)
        svc.db_service = None  # not used in delete_project

        report = svc.delete_project(session, project_id)

        assert report.success, f"Delete failed: {report.error_message}"
        assert report.lemmas_deleted == 5
        assert report.sentences_deleted == 3

        raw = sqlite3.connect(str(db_path))
        try:
            assert raw.execute(
                "SELECT COUNT(*) FROM dict_project WHERE project_id=?", (project_id,)
            ).fetchone()[0] == 0
            assert raw.execute(
                "SELECT COUNT(*) FROM lemma WHERE project_id=?", (project_id,)
            ).fetchone()[0] == 0
            assert raw.execute(
                "SELECT COUNT(*) FROM source_corpus WHERE project_id=?", (project_id,)
            ).fetchone()[0] == 0
            assert raw.execute(
                "SELECT COUNT(*) FROM document_sentence"
            ).fetchone()[0] == 0
        finally:
            raw.close()
    finally:
        session.close()
        engine.dispose()
        db_path.unlink(missing_ok=True)


def test_foreign_keys_restored_after_delete():
    """FK enforcement must be ON after delete_project completes."""
    db_path, session, project_id, engine = _make_test_db()
    try:
        svc = ProjectService.__new__(ProjectService)
        svc.db_service = None

        report = svc.delete_project(session, project_id)
        assert report.success

        result = session.execute(text("PRAGMA foreign_keys")).fetchone()
        assert result[0] == 1, "foreign_keys must be ON after delete_project"
    finally:
        session.close()
        engine.dispose()
        db_path.unlink(missing_ok=True)


def test_delete_nonexistent_project_returns_failure():
    db_path, session, _project_id, engine = _make_test_db()
    try:
        svc = ProjectService.__new__(ProjectService)
        svc.db_service = None

        report = svc.delete_project(session, project_id=99999)
        assert not report.success
        assert report.error_message == "Project not found"
    finally:
        session.close()
        engine.dispose()
        db_path.unlink(missing_ok=True)
