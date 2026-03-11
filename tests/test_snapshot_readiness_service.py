from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from app.infra.nlp_snapshot_codec import build_sentence_text_hash
from app.infra.sa_models import (
    DictProject,
    DocumentSentence,
    Library,
    ProcessorRun,
    SentenceNLPSnapshot,
    SourceCorpus,
    SourceDocument,
)
from app.services.db_service import DBService
from app.services.snapshot_readiness_service import SnapshotReadinessService


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


def _seed_snapshot_project(session) -> int:
    lib = Library(name="L")
    session.add(lib)
    session.flush()

    project = DictProject(
        library_id=lib.library_id,
        name="Snapshot Project",
        src_lang="he",
        tgt_lang="ru",
        is_general_corpus=1,
    )
    session.add(project)
    session.flush()

    corpus = SourceCorpus(project_id=project.project_id, name="Corpus")
    session.add(corpus)
    session.flush()

    doc_specs = [
        ("d1.txt", 2, "processed"),
        ("d2.txt", 2, "processed"),
        ("d3.txt", 1, "processed"),
    ]
    sentence_ids = []
    for idx, (name, sentence_count, status) in enumerate(doc_specs, start=1):
        doc = SourceDocument(
            corpus_id=corpus.corpus_id,
            file_path=f"/tmp/{name}",
            file_name=name,
            file_ext=".txt",
            file_size_bytes=10,
            sha256=f"sha-{idx}",
            status=status,
            sentence_count=sentence_count,
            token_count=sentence_count * 2,
        )
        session.add(doc)
        session.flush()
        for sent_index in range(sentence_count):
            sentence = DocumentSentence(
                doc_id=doc.doc_id,
                corpus_id=corpus.corpus_id,
                sent_index=sent_index,
                text=f"doc {idx} sentence {sent_index}",
            )
            session.add(sentence)
            session.flush()
            sentence_ids.append(int(sentence.sentence_id))

    session.add_all(
        [
            SentenceNLPSnapshot(
                sentence_id=sentence_ids[0],
                engine="fake",
                engine_version="1",
                sentence_text_hash=build_sentence_text_hash("doc 1 sentence 0"),
                payload_json="[]",
                token_count=2,
            ),
            SentenceNLPSnapshot(
                sentence_id=sentence_ids[1],
                engine="fake",
                engine_version="1",
                sentence_text_hash=build_sentence_text_hash("doc 1 sentence 1"),
                payload_json="[]",
                token_count=2,
            ),
            SentenceNLPSnapshot(
                sentence_id=sentence_ids[2],
                engine="fake",
                engine_version="1",
                sentence_text_hash=build_sentence_text_hash("doc 2 sentence 0"),
                payload_json="[]",
                token_count=2,
            ),
        ]
    )
    session.add(
        ProcessorRun(
            project_id=project.project_id,
            engine="fake",
            engine_version="1",
            docs_total=3,
            docs_processed=2,
            docs_failed=0,
            chunks_total=1,
            chunks_completed=1,
            status="ok",
            stage="completed",
            last_doc_id=2,
            finished_at="2026-03-11T10:00:00.000000Z",
            note=json.dumps(
                {
                    "kind": "batch_nlp",
                    "source": "snapshot_backfill_cli",
                    "doc_count": 3,
                    "first_doc_id": 1,
                    "last_doc_id": 3,
                },
                sort_keys=True,
            ),
        )
    )
    session.commit()
    return int(project.project_id)


def test_snapshot_readiness_service_reports_coverage_and_latest_run() -> None:
    db_path = _init_temp_db()
    _reset_db_service()
    DBService.initialize(db_path)
    db = DBService.get_instance()

    try:
        with db.get_session() as session:
            project_id = _seed_snapshot_project(session)

        service = SnapshotReadinessService()
        with db.get_read_session() as session:
            summary = service.get_project_summary(session, project_id)

        assert summary.project_name == "Snapshot Project"
        assert summary.processed_docs == 3
        assert summary.fully_covered_docs == 1
        assert summary.zero_snapshot_docs == 1
        assert summary.partial_snapshot_docs == 1
        assert summary.remaining_uncovered_docs == 2
        assert summary.sentence_count_total == 5
        assert summary.snapshot_count_total == 3
        assert summary.sentence_coverage_pct == 60.0
        assert round(summary.doc_coverage_pct or 0.0, 4) == 33.3333
        assert summary.latest_backfill_run_id is not None
        assert summary.latest_backfill_status == "ok"
        assert summary.latest_backfill_stage == "completed"
        assert summary.latest_backfill_last_doc_id == 2
        assert summary.contract_state == "bounded_validated"
        assert "Full-scale validation remains deferred" in (summary.contract_note or "")
        assert "Observational only" in (summary.summary_note or "")
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)


def test_snapshot_readiness_service_uses_read_only_session_without_commit() -> None:
    db_path = _init_temp_db()
    _reset_db_service()
    DBService.initialize(db_path)
    db = DBService.get_instance()

    try:
        with db.get_session() as session:
            project_id = _seed_snapshot_project(session)

        service = SnapshotReadinessService()
        with db.get_read_session() as session:
            session.commit = lambda: (_ for _ in ()).throw(AssertionError("commit should not be called"))
            summary = service.get_project_summary(session, project_id)

        assert summary.project_id == project_id
        assert summary.latest_backfill_status == "ok"
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)
