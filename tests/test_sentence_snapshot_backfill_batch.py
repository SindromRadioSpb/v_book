from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import select

from app.infra.sa_models import (
    DictProject,
    DocumentSentence,
    DocumentText,
    Lemma,
    Library,
    ProcessorRun,
    RunError,
    SentenceNLPSnapshot,
    SentenceNLPSnapshotStage,
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


def _seed_processed_docs_without_snapshots(session, count: int = 3) -> list[int]:
    lib = Library(name="L")
    session.add(lib)
    session.flush()
    project = DictProject(library_id=lib.library_id, name="Snapshot Backfill", src_lang="he", tgt_lang="ru")
    session.add(project)
    session.flush()
    corpus = SourceCorpus(project_id=project.project_id, name="C")
    session.add(corpus)
    session.flush()

    doc_ids: list[int] = []
    for idx in range(count):
        doc = SourceDocument(
            corpus_id=corpus.corpus_id,
            file_path=f"/tmp/processed_{idx}.txt",
            file_name=f"processed_{idx}.txt",
            file_ext=".txt",
            file_size_bytes=10,
            sha256=f"sha_processed_{idx}",
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
        words = [word for word in str(text or "").split() if word]
        return [_Sentence([_Token(word, word, "X") for word in words])]

    def get_name(self):
        return "fake"

    def get_version(self):
        return "1"


def test_snapshot_backfill_batch_persists_missing_snapshots_without_touching_lemma_stats(monkeypatch) -> None:
    db_path = _init_temp_db()
    _reset_db_service()
    DBService.initialize(db_path)
    db = DBService.get_instance()

    try:
        service = ProcessService()
        monkeypatch.setattr(service, "get_nlp_engine", lambda **kwargs: _Engine())
        monkeypatch.setattr(
            service,
            "_run_snapshot_backfill_integrity_check",
            lambda **kwargs: {"ok": True, "quick_check_rows": ["ok"]},
        )

        with db.get_session() as session:
            doc_ids = _seed_processed_docs_without_snapshots(session, count=2)
            ok_count, err_count = service.backfill_sentence_snapshots_batch(
                session,
                doc_ids,
                use_mock=True,
                chunk_size=1,
                resume_latest=True,
                source_label="snapshot_backfill_test",
            )
            snapshots = session.execute(select(SentenceNLPSnapshot)).scalars().all()
            staged_rows = session.execute(select(SentenceNLPSnapshotStage)).scalars().all()
            docs = session.execute(
                select(SourceDocument).where(SourceDocument.doc_id.in_(doc_ids)).order_by(SourceDocument.doc_id.asc())
            ).scalars().all()
            lemmas = session.execute(select(Lemma)).scalars().all()

        assert (ok_count, err_count) == (2, 0)
        assert len(snapshots) == 4
        assert staged_rows == []
        assert all(str(doc.status) == "processed" for doc in docs)
        assert [str(doc.snapshot_stats_state or "") for doc in docs] == ["valid", "valid"]
        assert [int(doc.snapshot_sentence_count or 0) for doc in docs] == [2, 2]
        assert lemmas == []
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)


def test_snapshot_backfill_batch_resumes_cancelled_run(monkeypatch) -> None:
    db_path = _init_temp_db()
    _reset_db_service()
    DBService.initialize(db_path)
    db = DBService.get_instance()

    try:
        service = ProcessService()
        monkeypatch.setattr(service, "get_nlp_engine", lambda **kwargs: _Engine())
        monkeypatch.setattr(
            service,
            "_run_snapshot_backfill_integrity_check",
            lambda **kwargs: {"ok": True, "quick_check_rows": ["ok"]},
        )

        first_states: list[dict] = []
        cancel_state = {"stop": False}
        with db.get_session() as session:
            doc_ids = _seed_processed_docs_without_snapshots(session, count=3)

            def _progress(current: int, total: int, doc_name: str) -> None:
                _ = total, doc_name
                if current >= 2:
                    cancel_state["stop"] = True

            ok_1, err_1 = service.backfill_sentence_snapshots_batch(
                session,
                doc_ids,
                use_mock=True,
                chunk_size=1,
                progress_callback=_progress,
                state_callback=first_states.append,
                cancel_check=lambda: bool(cancel_state["stop"]),
                resume_latest=True,
                source_label="snapshot_backfill_test",
            )
            runs_after_first = session.execute(
                select(ProcessorRun).order_by(ProcessorRun.run_id.asc())
            ).scalars().all()
            staged_after_first = session.execute(select(SentenceNLPSnapshotStage)).scalars().all()

        assert (ok_1, err_1) == (1, 0)
        assert len(runs_after_first) == 1
        assert runs_after_first[0].status == "cancelled"
        assert runs_after_first[0].docs_processed == 1
        assert staged_after_first == []
        assert any(state.get("phase") == "cancelled" for state in first_states)

        second_states: list[dict] = []
        with db.get_session() as session:
            ok_2, err_2 = service.backfill_sentence_snapshots_batch(
                session,
                doc_ids,
                use_mock=True,
                chunk_size=1,
                state_callback=second_states.append,
                resume_latest=True,
                source_label="snapshot_backfill_test",
            )
            final_runs = session.execute(
                select(ProcessorRun).order_by(ProcessorRun.run_id.asc())
            ).scalars().all()
            snapshots = session.execute(select(SentenceNLPSnapshot)).scalars().all()

        assert (ok_2, err_2) == (2, 0)
        assert len(final_runs) == 1
        assert final_runs[0].status == "ok"
        assert final_runs[0].stage == "completed"
        assert final_runs[0].docs_total == 3
        assert final_runs[0].docs_processed == 3
        assert len(snapshots) == 6
        assert any(state.get("phase") == "resumed" for state in second_states)
        assert any(state.get("phase") == "completed" for state in second_states)
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)


def test_snapshot_backfill_batch_marks_run_failed_on_integrity_error(monkeypatch) -> None:
    db_path = _init_temp_db()
    _reset_db_service()
    DBService.initialize(db_path)
    db = DBService.get_instance()

    try:
        service = ProcessService()
        monkeypatch.setattr(service, "get_nlp_engine", lambda **kwargs: _Engine())
        monkeypatch.setattr(
            service,
            "_run_snapshot_backfill_integrity_check",
            lambda **kwargs: {"ok": False, "error": "database disk image is malformed"},
        )

        states: list[dict] = []
        with db.get_session() as session:
            doc_ids = _seed_processed_docs_without_snapshots(session, count=2)
            with pytest.raises(RuntimeError, match="database disk image is malformed"):
                service.backfill_sentence_snapshots_batch(
                    session,
                    doc_ids,
                    use_mock=True,
                    chunk_size=1,
                    state_callback=states.append,
                    resume_latest=True,
                    source_label="snapshot_backfill_test",
                )
            run = session.execute(
                select(ProcessorRun).order_by(ProcessorRun.run_id.desc())
            ).scalar_one()
            run_errors = session.execute(
                select(RunError).where(RunError.run_id == run.run_id).order_by(RunError.error_id.asc())
            ).scalars().all()

        assert run.status == "failed"
        assert run.stage == "failed_integrity"
        assert run.docs_total == 2
        assert run.docs_processed == 2
        assert "database disk image is malformed" in str(run.error_message)
        assert any(error.stage == "integrity_check" for error in run_errors)
        assert any(state.get("phase") == "verifying_integrity" for state in states)
        assert any(state.get("phase") == "failed" for state in states)
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)


def test_snapshot_backfill_batch_runs_segment_integrity_check_per_chunk(monkeypatch) -> None:
    db_path = _init_temp_db()
    _reset_db_service()
    DBService.initialize(db_path)
    db = DBService.get_instance()

    try:
        service = ProcessService()
        monkeypatch.setattr(service, "get_nlp_engine", lambda **kwargs: _Engine())
        monkeypatch.setattr(
            service,
            "_run_snapshot_backfill_integrity_check",
            lambda **kwargs: {"ok": True, "quick_check_rows": ["ok"]},
        )
        segment_calls: list[float] = []

        def _fake_segment_check(**kwargs):
            segment_calls.append(float(kwargs.get("quick_check_timeout_sec") or 0.0))
            return {"ok": True, "quick_check_rows": ["ok"], "quick_check_timed_out": False}

        monkeypatch.setattr(service, "_run_snapshot_backfill_segment_check", _fake_segment_check)

        with db.get_session() as session:
            doc_ids = _seed_processed_docs_without_snapshots(session, count=3)
            ok_count, err_count = service.backfill_sentence_snapshots_batch(
                session,
                doc_ids,
                use_mock=True,
                chunk_size=2,
                merge_batch_size=1,
                segment_quick_check_timeout=0.25,
                resume_latest=True,
                source_label="snapshot_backfill_test",
            )

        assert (ok_count, err_count) == (3, 0)
        assert segment_calls == [0.25, 0.25]
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)


def test_snapshot_backfill_batch_clears_stale_stage_rows_before_resume(monkeypatch) -> None:
    db_path = _init_temp_db()
    _reset_db_service()
    DBService.initialize(db_path)
    db = DBService.get_instance()

    try:
        service = ProcessService()
        monkeypatch.setattr(service, "get_nlp_engine", lambda **kwargs: _Engine())
        monkeypatch.setattr(
            service,
            "_run_snapshot_backfill_integrity_check",
            lambda **kwargs: {"ok": True, "quick_check_rows": ["ok"]},
        )
        monkeypatch.setattr(
            service,
            "_run_snapshot_backfill_segment_check",
            lambda **kwargs: {"ok": True, "quick_check_rows": ["ok"], "quick_check_timed_out": False},
        )

        with db.get_session() as session:
            doc_ids = _seed_processed_docs_without_snapshots(session, count=2)
            service.backfill_sentence_snapshots_batch(
                session,
                doc_ids,
                use_mock=True,
                chunk_size=1,
                resume_latest=True,
                source_label="snapshot_backfill_test",
            )
            run = session.execute(select(ProcessorRun).order_by(ProcessorRun.run_id.desc())).scalar_one()
            sentence_id = session.execute(
                select(DocumentSentence.sentence_id)
                .where(DocumentSentence.doc_id == doc_ids[1])
                .order_by(DocumentSentence.sent_index.asc())
            ).scalars().first()
            assert sentence_id is not None
            session.add(
                SentenceNLPSnapshotStage(
                    run_id=int(run.run_id),
                    sentence_id=int(sentence_id),
                    engine="fake",
                    engine_version="1",
                    sentence_text_hash="stale",
                    payload_json="[]",
                    token_count=0,
                )
            )
            run.status = "cancelled"
            run.stage = "cancelled"
            run.docs_processed = 1
            run.last_doc_id = doc_ids[0]
            session.commit()

            service.backfill_sentence_snapshots_batch(
                session,
                doc_ids,
                use_mock=True,
                chunk_size=1,
                resume_latest=True,
                source_label="snapshot_backfill_test",
            )
            staged_rows = session.execute(select(SentenceNLPSnapshotStage)).scalars().all()

        assert staged_rows == []
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)


def test_snapshot_backfill_batch_passes_integrity_checkpoint_mode(monkeypatch) -> None:
    db_path = _init_temp_db()
    _reset_db_service()
    DBService.initialize(db_path)
    db = DBService.get_instance()

    try:
        service = ProcessService()
        monkeypatch.setattr(service, "get_nlp_engine", lambda **kwargs: _Engine())
        captured: dict[str, str] = {}

        def _fake_integrity_check(**kwargs):
            captured["checkpoint_mode"] = str(kwargs.get("checkpoint_mode"))
            return {"ok": True, "quick_check_rows": ["ok"]}

        monkeypatch.setattr(
            service,
            "_run_snapshot_backfill_integrity_check",
            _fake_integrity_check,
        )

        with db.get_session() as session:
            doc_ids = _seed_processed_docs_without_snapshots(session, count=2)
            ok_count, err_count = service.backfill_sentence_snapshots_batch(
                session,
                doc_ids,
                use_mock=True,
                chunk_size=1,
                resume_latest=True,
                source_label="snapshot_backfill_test",
                integrity_checkpoint_mode="none",
            )

        assert (ok_count, err_count) == (2, 0)
        assert captured["checkpoint_mode"] == "none"
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)


def test_snapshot_backfill_batch_defaults_integrity_checkpoint_mode_to_none(monkeypatch) -> None:
    db_path = _init_temp_db()
    _reset_db_service()
    DBService.initialize(db_path)
    db = DBService.get_instance()

    try:
        service = ProcessService()
        monkeypatch.setattr(service, "get_nlp_engine", lambda **kwargs: _Engine())
        captured: dict[str, str] = {}

        def _fake_integrity_check(**kwargs):
            captured["checkpoint_mode"] = str(kwargs.get("checkpoint_mode"))
            return {"ok": True, "quick_check_rows": ["ok"]}

        monkeypatch.setattr(
            service,
            "_run_snapshot_backfill_integrity_check",
            _fake_integrity_check,
        )

        with db.get_session() as session:
            doc_ids = _seed_processed_docs_without_snapshots(session, count=1)
            ok_count, err_count = service.backfill_sentence_snapshots_batch(
                session,
                doc_ids,
                use_mock=True,
                chunk_size=1,
                resume_latest=True,
                source_label="snapshot_backfill_test",
            )

        assert (ok_count, err_count) == (1, 0)
        assert captured["checkpoint_mode"] == "none"
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)
