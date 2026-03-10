from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import select

from app.infra.sa_models import (
    DictProject,
    DocumentSentence,
    DocumentText,
    Library,
    ProcessorRun,
    SentenceNLPSnapshot,
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


def _seed_reference_docs(session, count: int = 3) -> tuple[int, list[int]]:
    lib = Library(name="L")
    session.add(lib)
    session.flush()
    project = DictProject(
        library_id=lib.library_id,
        name="Reference NLP",
        src_lang="he",
        tgt_lang="ru",
        is_general_corpus=1,
    )
    session.add(project)
    session.flush()
    corpus = SourceCorpus(project_id=project.project_id, name="Reference Corpus")
    session.add(corpus)
    session.flush()

    doc_ids: list[int] = []
    for idx in range(count):
        doc = SourceDocument(
            corpus_id=corpus.corpus_id,
            file_path=f"/tmp/ref_{idx}.txt",
            file_name=f"ref_{idx}.txt",
            file_ext=".txt",
            file_size_bytes=10,
            sha256=f"sha_ref_{idx}",
            status="imported",
        )
        session.add(doc)
        session.flush()
        session.add(DocumentText(doc_id=doc.doc_id, raw_text=f"shalom ref {idx}"))
        doc_ids.append(int(doc.doc_id))
    session.commit()
    return int(project.project_id), doc_ids


def _seed_processed_reference_docs_without_snapshots(session, count: int = 3) -> tuple[int, list[int]]:
    lib = Library(name="L")
    session.add(lib)
    session.flush()
    project = DictProject(
        library_id=lib.library_id,
        name="Reference Backfill",
        src_lang="he",
        tgt_lang="ru",
        is_general_corpus=1,
    )
    session.add(project)
    session.flush()
    corpus = SourceCorpus(project_id=project.project_id, name="Reference Corpus")
    session.add(corpus)
    session.flush()

    doc_ids: list[int] = []
    for idx in range(count):
        doc = SourceDocument(
            corpus_id=corpus.corpus_id,
            file_path=f"/tmp/ref_processed_{idx}.txt",
            file_name=f"ref_processed_{idx}.txt",
            file_ext=".txt",
            file_size_bytes=10,
            sha256=f"sha_ref_processed_{idx}",
            status="processed",
            sentence_count=2,
        )
        session.add(doc)
        session.flush()
        session.add(DocumentText(doc_id=doc.doc_id, raw_text=f"alpha {idx}. beta {idx}"))
        session.add(
            DocumentSentence(
                doc_id=doc.doc_id,
                sent_index=0,
                text=f"alpha {idx}",
                corpus_id=corpus.corpus_id,
            )
        )
        session.add(
            DocumentSentence(
                doc_id=doc.doc_id,
                sent_index=1,
                text=f"beta {idx}",
                corpus_id=corpus.corpus_id,
            )
        )
        doc_ids.append(int(doc.doc_id))
    session.commit()
    return int(project.project_id), doc_ids


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


def _create_cancelled_reference_run(db_path: Path, monkeypatch) -> tuple[int, int, list[int]]:
    _reset_db_service()
    DBService.initialize(db_path)
    db = DBService.get_instance()
    service = ProcessService()
    monkeypatch.setattr(ProcessService, "get_nlp_engine", lambda self, **kwargs: _Engine())

    cancel_state = {"stop": False}
    try:
        with db.get_session() as session:
            project_id, doc_ids = _seed_reference_docs(session, count=3)

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
                source_label="reference_cli",
            )
            run = session.execute(select(ProcessorRun).order_by(ProcessorRun.run_id.desc())).scalar_one()
            return int(project_id), int(run.run_id), doc_ids
    finally:
        _reset_db_service()


def _create_cancelled_snapshot_backfill_run(db_path: Path, monkeypatch) -> tuple[int, int, list[int]]:
    _reset_db_service()
    DBService.initialize(db_path)
    db = DBService.get_instance()
    service = ProcessService()
    monkeypatch.setattr(ProcessService, "get_nlp_engine", lambda self, **kwargs: _Engine())

    cancel_state = {"stop": False}
    try:
        with db.get_session() as session:
            project_id, doc_ids = _seed_processed_reference_docs_without_snapshots(session, count=3)

            def _progress(current: int, total: int, doc_name: str) -> None:
                _ = total, doc_name
                if current >= 2:
                    cancel_state["stop"] = True

            service.backfill_sentence_snapshots_batch(
                session,
                doc_ids,
                use_mock=True,
                chunk_size=1,
                progress_callback=_progress,
                cancel_check=lambda: bool(cancel_state["stop"]),
                resume_latest=True,
                source_label="snapshot_backfill_cli",
            )
            run = session.execute(select(ProcessorRun).order_by(ProcessorRun.run_id.desc())).scalar_one()
            return int(project_id), int(run.run_id), doc_ids
    finally:
        _reset_db_service()


def _load_script_module():
    scripts_dir = str((Path(__file__).resolve().parent.parent / "scripts"))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import process_reference_corpus

    return process_reference_corpus


def test_cli_rejects_conflicting_resume_flags(monkeypatch):
    module = _load_script_module()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "process_reference_corpus.py",
            "--db-path",
            "dummy.db",
            "--project-id",
            "1",
            "--resume-latest",
            "--resume-run-id",
            "10",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 2


def test_cli_verify_only_explicit_run_id_exits_zero_without_processing(monkeypatch):
    db_path = _init_temp_db()
    try:
        project_id, run_id, _doc_ids = _create_cancelled_reference_run(db_path, monkeypatch)
        module = _load_script_module()

        def _unexpected_process(*args, **kwargs):
            raise AssertionError("verify-only must not call process_documents_batch")

        monkeypatch.setattr(ProcessService, "process_documents_batch", _unexpected_process)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "process_reference_corpus.py",
                "--db-path",
                str(db_path),
                "--project-id",
                str(project_id),
                "--resume-run-id",
                str(run_id),
                "--verify-only",
            ],
        )

        module.main()
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)


def test_cli_verify_only_exits_three_on_contract_mismatch(monkeypatch):
    db_path = _init_temp_db()
    try:
        project_id, run_id, _doc_ids = _create_cancelled_reference_run(db_path, monkeypatch)
        module = _load_script_module()

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "process_reference_corpus.py",
                "--db-path",
                str(db_path),
                "--project-id",
                str(project_id),
                "--resume-run-id",
                str(run_id),
                "--verify-only",
                "--max-docs",
                "2",
            ],
        )

        with pytest.raises(SystemExit) as exc:
            module.main()
        assert exc.value.code == 3
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)


def test_cli_resume_run_id_resumes_selected_run(monkeypatch):
    db_path = _init_temp_db()
    try:
        project_id, run_id, _doc_ids = _create_cancelled_reference_run(db_path, monkeypatch)
        module = _load_script_module()

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "process_reference_corpus.py",
                "--db-path",
                str(db_path),
                "--project-id",
                str(project_id),
                "--resume-run-id",
                str(run_id),
            ],
        )

        module.main()

        _reset_db_service()
        DBService.initialize(db_path)
        db = DBService.get_instance()
        with db.get_session() as session:
            run = session.get(ProcessorRun, int(run_id))
            assert run is not None
            assert run.status == "ok"
            assert run.stage == "completed"
            assert run.docs_total == 3
            assert run.docs_processed == 3
            assert run.chunks_completed == 3
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)


def test_cli_verify_only_snapshot_backfill_run_exits_zero_without_processing(monkeypatch):
    db_path = _init_temp_db()
    try:
        project_id, run_id, _doc_ids = _create_cancelled_snapshot_backfill_run(db_path, monkeypatch)
        module = _load_script_module()

        def _unexpected_backfill(*args, **kwargs):
            raise AssertionError("verify-only must not call backfill_sentence_snapshots_batch")

        monkeypatch.setattr(ProcessService, "backfill_sentence_snapshots_batch", _unexpected_backfill)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "process_reference_corpus.py",
                "--db-path",
                str(db_path),
                "--project-id",
                str(project_id),
                "--backfill-snapshots",
                "--resume-run-id",
                str(run_id),
                "--verify-only",
            ],
        )

        module.main()
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)


def test_cli_coverage_only_snapshot_backfill_is_read_only(monkeypatch):
    db_path = _init_temp_db()
    try:
        _reset_db_service()
        DBService.initialize(db_path)
        db = DBService.get_instance()
        with db.get_session() as session:
            project_id, _doc_ids = _seed_processed_reference_docs_without_snapshots(session, count=2)
        _reset_db_service()

        module = _load_script_module()
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "process_reference_corpus.py",
                "--db-path",
                str(db_path),
                "--project-id",
                str(project_id),
                "--backfill-snapshots",
                "--coverage-only",
            ],
        )

        module.main()

        _reset_db_service()
        DBService.initialize(db_path)
        db = DBService.get_instance()
        with db.get_session() as session:
            snapshots = session.execute(select(SentenceNLPSnapshot)).scalars().all()
        assert snapshots == []
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)


def test_cli_snapshot_backfill_exits_two_on_integrity_failure(monkeypatch):
    db_path = _init_temp_db()
    try:
        _reset_db_service()
        DBService.initialize(db_path)
        db = DBService.get_instance()
        with db.get_session() as session:
            project_id, _doc_ids = _seed_processed_reference_docs_without_snapshots(session, count=2)
        _reset_db_service()

        module = _load_script_module()

        def _raise_integrity_failure(*args, **kwargs):
            raise RuntimeError("database disk image is malformed")

        monkeypatch.setattr(ProcessService, "backfill_sentence_snapshots_batch", _raise_integrity_failure)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "process_reference_corpus.py",
                "--db-path",
                str(db_path),
                "--project-id",
                str(project_id),
                "--backfill-snapshots",
            ],
        )

        with pytest.raises(SystemExit) as exc:
            module.main()
        assert exc.value.code == 2
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)
