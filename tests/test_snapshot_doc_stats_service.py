from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from sqlalchemy import inspect, select

from app.infra.sa_models import (
    DictProject,
    DocumentSentence,
    Library,
    SentenceNLPSnapshot,
    SourceCorpus,
    SourceDocument,
)
from app.services.db_service import DBService
from app.services.snapshot_doc_stats_service import SnapshotDocStatsService


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


def _seed_docs(session) -> list[int]:
    lib = Library(name="L")
    session.add(lib)
    session.flush()
    project = DictProject(library_id=lib.library_id, name="P", src_lang="he", tgt_lang="ru")
    session.add(project)
    session.flush()
    corpus = SourceCorpus(project_id=project.project_id, name="C")
    session.add(corpus)
    session.flush()

    docs: list[SourceDocument] = []
    for idx, sentence_count in enumerate((2, 1), start=1):
        doc = SourceDocument(
            corpus_id=corpus.corpus_id,
            file_path=f"/tmp/{idx}.txt",
            file_name=f"{idx}.txt",
            file_ext=".txt",
            file_size_bytes=10,
            sha256=f"sha-{idx}",
            status="processed",
            sentence_count=sentence_count,
        )
        session.add(doc)
        session.flush()
        docs.append(doc)

    for sent_index in range(2):
        sentence = DocumentSentence(
            doc_id=docs[0].doc_id,
            corpus_id=corpus.corpus_id,
            sent_index=sent_index,
            text=f"alpha {sent_index}",
        )
        session.add(sentence)
        session.flush()
        if sent_index == 0:
            session.add(
                SentenceNLPSnapshot(
                    sentence_id=sentence.sentence_id,
                    engine="fake",
                    engine_version="1",
                    sentence_text_hash=f"hash-{sent_index}",
                    payload_json="[]",
                    token_count=1,
                )
            )

    sentence = DocumentSentence(
        doc_id=docs[1].doc_id,
        corpus_id=corpus.corpus_id,
        sent_index=0,
        text="beta 0",
    )
    session.add(sentence)
    session.flush()
    session.commit()
    return [int(doc.doc_id) for doc in docs]


def test_snapshot_doc_stats_migration_adds_source_document_columns() -> None:
    db_path = _init_temp_db()
    _reset_db_service()
    DBService.initialize(db_path)
    db = DBService.get_instance()

    try:
        inspector = inspect(db.db_manager.engine)
        columns = {column["name"] for column in inspector.get_columns("source_document")}
        assert "snapshot_sentence_count" in columns
        assert "snapshot_stats_state" in columns
        assert "snapshot_stats_updated_at" in columns
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)


def test_snapshot_doc_stats_refresh_and_verify_detects_drift() -> None:
    db_path = _init_temp_db()
    _reset_db_service()
    DBService.initialize(db_path)
    db = DBService.get_instance()

    try:
        service = SnapshotDocStatsService()
        with db.get_session() as session:
            doc_ids = _seed_docs(session)
            refresh = service.refresh_document_stats(session, doc_ids)
            session.commit()
            docs = (
                session.execute(
                    select(SourceDocument)
                    .where(SourceDocument.doc_id.in_(doc_ids))
                    .order_by(SourceDocument.doc_id.asc())
                )
                .scalars()
                .all()
            )

        assert refresh.docs_seen == 2
        assert refresh.docs_valid == 2
        assert refresh.docs_invalid == 0
        assert [int(doc.snapshot_sentence_count or 0) for doc in docs] == [1, 0]
        assert [str(doc.snapshot_stats_state or "") for doc in docs] == ["valid", "valid"]

        with db.get_session() as session:
            doc = session.get(SourceDocument, int(doc_ids[0]))
            assert doc is not None
            doc.snapshot_sentence_count = 99
            session.commit()

        with db.get_read_session() as session:
            verification = service.verify_document_stats(session, doc_ids)

        assert verification.docs_checked == 2
        assert verification.docs_with_drift == 1
        assert verification.snapshot_count_mismatches == 1
        assert verification.sample_doc_ids == [int(doc_ids[0])]
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)
