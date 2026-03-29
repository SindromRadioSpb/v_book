from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from sqlalchemy import select

from app.infra.db_path_resolver import get_supported_schema_version
from app.infra.sa_models import (
    DictProject,
    DocumentText,
    Library,
    ProcessorRun,
    RunError,
    SourceCorpus,
    SourceDocument,
)
from app.services.db_service import DBService
from app.services.process_service import ProcessService


def _reset_db_service() -> None:
    DBService.shutdown()
    DBService._instance = None
    DBService._db_manager = None
    DBService._ref_managers = {}


def _init_temp_db() -> Path:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    conn = sqlite3.connect(str(db_path))
    try:
        migrations_dir = Path("app/infra/migrations")
        for migration_file in sorted(migrations_dir.glob("*.sql")):
            conn.executescript(migration_file.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()
    return db_path


def _seed_project(session) -> tuple[int, int]:
    lib = Library(name="L")
    session.add(lib)
    session.flush()
    project = DictProject(library_id=lib.library_id, name="P", src_lang="he", tgt_lang="ru")
    session.add(project)
    session.flush()
    corpus = SourceCorpus(project_id=project.project_id, name="C")
    session.add(corpus)
    session.flush()
    return int(project.project_id), int(corpus.corpus_id)


def test_processor_run_migration_adds_run_state_columns() -> None:
    db_path = _init_temp_db()
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            schema_version = int(
                conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[
                    0
                ]
            )
            columns = [
                row[1] for row in conn.execute("PRAGMA table_info('processor_run')").fetchall()
            ]
        finally:
            conn.close()

        assert schema_version == get_supported_schema_version()
        for required in (
            "docs_total",
            "docs_failed",
            "chunks_total",
            "chunks_completed",
            "stage",
            "last_doc_id",
            "params_hash",
            "configured_engine_id",
            "effective_engine_id",
            "fallback_used",
            "runtime_reason_code",
            "runtime_mode",
            "runtime_probe_summary_json",
            "error_message",
        ):
            assert required in columns
    finally:
        db_path.unlink(missing_ok=True)


def test_recover_from_crash_only_marks_running_runs_failed() -> None:
    db_path = _init_temp_db()
    _reset_db_service()
    DBService.initialize(db_path)
    db = DBService.get_instance()

    try:
        with db.get_session() as session:
            project_id, _ = _seed_project(session)
            session.add_all(
                [
                    ProcessorRun(
                        project_id=project_id,
                        engine="mock",
                        status="running",
                        stage="processing",
                        docs_total=10,
                        chunks_total=2,
                    ),
                    ProcessorRun(
                        project_id=project_id,
                        engine="mock",
                        status="paused",
                        stage="processing",
                        docs_total=10,
                        docs_processed=4,
                        chunks_total=2,
                        chunks_completed=1,
                    ),
                    ProcessorRun(
                        project_id=project_id,
                        engine="mock",
                        status="cancelled",
                        stage="processing",
                        docs_total=10,
                        docs_processed=4,
                        docs_failed=1,
                        chunks_total=2,
                        chunks_completed=1,
                    ),
                ]
            )
            session.commit()

        recovered = db.recover_from_crash()
        assert recovered == 1

        with db.get_session() as session:
            runs = (
                session.execute(select(ProcessorRun).order_by(ProcessorRun.run_id)).scalars().all()
            )
            errors = session.execute(select(RunError).order_by(RunError.error_id)).scalars().all()

        assert runs[0].status == "failed"
        assert runs[0].stage == "failed"
        assert runs[0].error_message == "Process terminated unexpectedly - recovered on restart"
        assert runs[1].status == "paused"
        assert runs[2].status == "cancelled"
        assert len(errors) == 1
        assert errors[0].stage == "crash_recovery"
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)


def test_process_document_populates_extended_run_state(monkeypatch) -> None:
    db_path = _init_temp_db()
    _reset_db_service()
    DBService.initialize(db_path)
    db = DBService.get_instance()

    class _Token:
        def __init__(self, text: str, lemma: str, pos: str):
            self.text = text
            self.lemma = lemma
            self.pos = pos

    class _Sentence:
        def __init__(self, tokens):
            self.tokens = tokens

    class _Engine:
        def process(self, text: str):
            _ = text
            return [_Sentence([_Token("shalom", "shalom", "INTJ")])]

        def get_name(self):
            return "fake"

        def get_version(self):
            return "1"

    try:
        service = ProcessService()
        monkeypatch.setattr(service, "get_nlp_engine", lambda **kwargs: _Engine())

        with db.get_session() as session:
            project_id, corpus_id = _seed_project(session)
            doc = SourceDocument(
                corpus_id=corpus_id,
                file_path="/tmp/a.txt",
                file_name="a.txt",
                file_ext=".txt",
                file_size_bytes=10,
                sha256="sha1",
                status="imported",
            )
            session.add(doc)
            session.flush()
            doc_id = int(doc.doc_id)
            session.add(DocumentText(doc_id=doc.doc_id, raw_text="shalom"))
            session.commit()

            assert service.process_document(session, doc_id, use_mock=True) is True
            run = session.execute(
                select(ProcessorRun).order_by(ProcessorRun.run_id.desc())
            ).scalar_one()

        assert run.project_id == project_id
        assert run.status == "ok"
        assert run.stage == "completed"
        assert run.docs_total == 1
        assert run.docs_processed == 1
        assert run.docs_failed == 0
        assert run.chunks_total == 1
        assert run.chunks_completed == 1
        assert run.last_doc_id == doc_id
        assert run.params_hash
        assert run.configured_engine_id == "mock"
        assert run.effective_engine_id == "mock"
        assert run.fallback_used is False
        assert run.runtime_reason_code is None
        assert run.runtime_mode == "cpu"
        assert run.runtime_probe_summary_json
        assert run.error_message is None
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)


def test_process_document_failure_records_extended_run_state(monkeypatch) -> None:
    db_path = _init_temp_db()
    _reset_db_service()
    DBService.initialize(db_path)
    db = DBService.get_instance()

    class _Engine:
        def process(self, text: str):
            _ = text
            return []

        def get_name(self):
            return "fake"

        def get_version(self):
            return "1"

    try:
        service = ProcessService()
        monkeypatch.setattr(service, "get_nlp_engine", lambda **kwargs: _Engine())

        with db.get_session() as session:
            _, corpus_id = _seed_project(session)
            doc = SourceDocument(
                corpus_id=corpus_id,
                file_path="/tmp/a.txt",
                file_name="a.txt",
                file_ext=".txt",
                file_size_bytes=10,
                sha256="sha1",
                status="imported",
            )
            session.add(doc)
            session.flush()
            doc_id = int(doc.doc_id)
            session.commit()

            assert service.process_document(session, doc_id, use_mock=True) is False
            run = session.execute(
                select(ProcessorRun).order_by(ProcessorRun.run_id.desc())
            ).scalar_one()
            errors = session.execute(select(RunError).order_by(RunError.error_id)).scalars().all()

        assert run.status == "failed"
        assert run.stage == "failed"
        assert run.docs_total == 1
        assert run.docs_processed == 0
        assert run.docs_failed == 1
        assert run.chunks_total == 1
        assert run.chunks_completed == 0
        assert run.last_doc_id == doc_id
        assert run.error_message == "No text available for document"
        assert len(errors) == 1
        assert errors[0].stage == "processing"
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)
