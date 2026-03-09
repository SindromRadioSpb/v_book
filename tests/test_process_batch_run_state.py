from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from sqlalchemy import select

from app.infra.sa_models import (
    DictProject,
    DocumentText,
    Library,
    ProcessorRun,
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
        for migration_file in sorted(Path("app/infra/migrations").glob("*.sql")):
            conn.executescript(migration_file.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()
    return db_path


def _seed_docs(session, count: int = 3) -> list[int]:
    lib = Library(name="L")
    session.add(lib)
    session.flush()
    project = DictProject(library_id=lib.library_id, name="P", src_lang="he", tgt_lang="ru")
    session.add(project)
    session.flush()
    corpus = SourceCorpus(project_id=project.project_id, name="C")
    session.add(corpus)
    session.flush()

    doc_ids: list[int] = []
    for idx in range(count):
        doc = SourceDocument(
            corpus_id=corpus.corpus_id,
            file_path=f"/tmp/{idx}.txt",
            file_name=f"doc_{idx}.txt",
            file_ext=".txt",
            file_size_bytes=10,
            sha256=f"sha_{idx}",
            status="imported",
        )
        session.add(doc)
        session.flush()
        session.add(DocumentText(doc_id=doc.doc_id, raw_text=f"shalom {idx}"))
        doc_ids.append(int(doc.doc_id))
    session.commit()
    return doc_ids


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
        return [_Sentence([_Token(text, text, "X")])]

    def get_name(self):
        return "fake"

    def get_version(self):
        return "1"


def test_batch_run_resumes_latest_cancelled_run(monkeypatch) -> None:
    db_path = _init_temp_db()
    _reset_db_service()
    DBService.initialize(db_path)
    db = DBService.get_instance()

    try:
        service = ProcessService()
        monkeypatch.setattr(service, "get_nlp_engine", lambda **kwargs: _Engine())

        first_states: list[dict] = []
        first_progress: list[tuple[int, int, str]] = []
        cancel_state = {"stop": False}

        with db.get_session() as session:
            doc_ids = _seed_docs(session, count=3)

            def _progress(current: int, total: int, doc_name: str) -> None:
                first_progress.append((current, total, doc_name))
                if current >= 2:
                    cancel_state["stop"] = True

            ok_1, err_1 = service.process_documents_batch(
                session,
                doc_ids,
                use_mock=True,
                chunk_size=1,
                progress_callback=_progress,
                state_callback=first_states.append,
                cancel_check=lambda: bool(cancel_state["stop"]),
                resume_latest=True,
                source_label="test_batch",
            )

            runs_after_first = session.execute(
                select(ProcessorRun).order_by(ProcessorRun.run_id)
            ).scalars().all()

        assert (ok_1, err_1) == (1, 0)
        assert len(runs_after_first) == 1
        assert runs_after_first[0].status == "cancelled"
        assert runs_after_first[0].docs_processed == 1
        assert runs_after_first[0].last_doc_id == doc_ids[0]
        assert any(state.get("phase") == "cancelled" for state in first_states)

        second_states: list[dict] = []
        with db.get_session() as session:
            ok_2, err_2 = service.process_documents_batch(
                session,
                doc_ids,
                use_mock=True,
                chunk_size=1,
                state_callback=second_states.append,
                resume_latest=True,
                source_label="test_batch",
            )
            final_runs = session.execute(
                select(ProcessorRun).order_by(ProcessorRun.run_id)
            ).scalars().all()

        assert (ok_2, err_2) == (2, 0)
        assert len(final_runs) == 1
        assert final_runs[0].status == "ok"
        assert final_runs[0].stage == "completed"
        assert final_runs[0].docs_total == 3
        assert final_runs[0].docs_processed == 3
        assert final_runs[0].docs_failed == 0
        assert final_runs[0].chunks_completed == 3
        assert any(state.get("phase") == "resumed" for state in second_states)
        assert any(state.get("phase") == "completed" for state in second_states)
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)


def test_batch_run_does_not_resume_when_doc_contract_changes(monkeypatch) -> None:
    db_path = _init_temp_db()
    _reset_db_service()
    DBService.initialize(db_path)
    db = DBService.get_instance()

    try:
        service = ProcessService()
        monkeypatch.setattr(service, "get_nlp_engine", lambda **kwargs: _Engine())

        cancel_state = {"stop": False}
        with db.get_session() as session:
            doc_ids = _seed_docs(session, count=3)

            def _progress(current: int, total: int, doc_name: str) -> None:
                _ = total, doc_name
                if current >= 2:
                    cancel_state["stop"] = True

            service.process_documents_batch(
                session,
                doc_ids,
                use_mock=True,
                chunk_size=1,
                progress_callback=_progress,
                cancel_check=lambda: bool(cancel_state["stop"]),
                resume_latest=True,
                source_label="test_batch",
            )

        with db.get_session() as session:
            ok_2, err_2 = service.process_documents_batch(
                session,
                doc_ids[1:],
                use_mock=True,
                chunk_size=1,
                resume_latest=True,
                source_label="test_batch",
            )
            runs = session.execute(select(ProcessorRun).order_by(ProcessorRun.run_id)).scalars().all()

        assert (ok_2, err_2) == (2, 0)
        assert len(runs) == 2
        assert runs[0].status == "cancelled"
        assert runs[1].status == "ok"
        assert runs[1].docs_total == 2
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)


def test_batch_resume_keeps_original_chunk_contract(monkeypatch) -> None:
    db_path = _init_temp_db()
    _reset_db_service()
    DBService.initialize(db_path)
    db = DBService.get_instance()

    try:
        service = ProcessService()
        monkeypatch.setattr(service, "get_nlp_engine", lambda **kwargs: _Engine())

        cancel_state = {"stop": False}
        with db.get_session() as session:
            doc_ids = _seed_docs(session, count=2)

            def _progress(current: int, total: int, doc_name: str) -> None:
                _ = total, doc_name
                if current >= 2:
                    cancel_state["stop"] = True

            service.process_documents_batch(
                session,
                doc_ids,
                use_mock=True,
                chunk_size=1,
                progress_callback=_progress,
                cancel_check=lambda: bool(cancel_state["stop"]),
                resume_latest=True,
                source_label="test_batch",
            )

        with db.get_session() as session:
            ok_2, err_2 = service.process_documents_batch(
                session,
                doc_ids,
                use_mock=True,
                chunk_size=50,
                resume_latest=True,
                source_label="test_batch",
            )
            runs = session.execute(select(ProcessorRun).order_by(ProcessorRun.run_id)).scalars().all()

        assert (ok_2, err_2) == (1, 0)
        assert len(runs) == 1
        assert runs[0].status == "ok"
        assert runs[0].chunks_total == 2
        assert runs[0].chunks_completed == 2
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)


def test_batch_run_does_not_resume_when_doc_ids_hash_changes(monkeypatch) -> None:
    db_path = _init_temp_db()
    _reset_db_service()
    DBService.initialize(db_path)
    db = DBService.get_instance()

    try:
        service = ProcessService()
        monkeypatch.setattr(service, "get_nlp_engine", lambda **kwargs: _Engine())

        cancel_state = {"stop": False}
        with db.get_session() as session:
            doc_ids = _seed_docs(session, count=4)

            def _progress(current: int, total: int, doc_name: str) -> None:
                _ = total, doc_name
                if current >= 1:
                    cancel_state["stop"] = True

            service.process_documents_batch(
                session,
                [doc_ids[0], doc_ids[1], doc_ids[3]],
                use_mock=True,
                chunk_size=1,
                progress_callback=_progress,
                cancel_check=lambda: bool(cancel_state["stop"]),
                resume_latest=True,
                source_label="test_batch",
            )

        with db.get_session() as session:
            ok_2, err_2 = service.process_documents_batch(
                session,
                [doc_ids[0], doc_ids[2], doc_ids[3]],
                use_mock=True,
                chunk_size=1,
                resume_latest=True,
                source_label="test_batch",
            )
            runs = session.execute(select(ProcessorRun).order_by(ProcessorRun.run_id)).scalars().all()

        assert (ok_2, err_2) == (3, 0)
        assert len(runs) == 2
        assert runs[0].status == "cancelled"
        assert runs[1].status == "ok"
        assert runs[1].docs_total == 3
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)


def test_batch_reprocess_uses_batch_run_without_extra_per_doc_runs(monkeypatch) -> None:
    db_path = _init_temp_db()
    _reset_db_service()
    DBService.initialize(db_path)
    db = DBService.get_instance()

    try:
        service = ProcessService()
        monkeypatch.setattr(service, "get_nlp_engine", lambda **kwargs: _Engine())

        with db.get_session() as session:
            doc_ids = _seed_docs(session, count=2)
            for doc_id in doc_ids:
                ok = service.process_document(session, doc_id, use_mock=True, track_run=False)
                assert ok is True

        with db.get_session() as session:
            ok_2, err_2 = service.process_documents_batch(
                session,
                doc_ids,
                use_mock=True,
                is_reprocess=True,
                chunk_size=1,
                resume_latest=True,
                source_label="test_batch",
            )
            runs = session.execute(select(ProcessorRun).order_by(ProcessorRun.run_id)).scalars().all()

        assert (ok_2, err_2) == (2, 0)
        assert len(runs) == 1
        assert runs[0].status == "ok"
        assert runs[0].docs_total == 2
        assert runs[0].docs_processed == 2
        assert runs[0].chunks_total == 2
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)
