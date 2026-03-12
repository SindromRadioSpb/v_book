from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from app.infra.sa_models import (
    DictProject,
    Library,
    ProcessorRun,
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


def _seed_snapshot_project(session) -> tuple[int, int, int]:
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
    snapshot_counts = (2, 1, 0)
    for idx, ((name, sentence_count, status), snapshot_count) in enumerate(
        zip(doc_specs, snapshot_counts),
        start=1,
    ):
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
            snapshot_sentence_count=int(snapshot_count),
            snapshot_stats_state="valid",
        )
        session.add(doc)
        session.flush()
    bounded_run = ProcessorRun(
        project_id=project.project_id,
        engine="fake",
        engine_version="1",
        docs_total=12000,
        docs_processed=12000,
        docs_failed=0,
        chunks_total=12,
        chunks_completed=12,
        status="ok",
        stage="completed",
        last_doc_id=12000,
        finished_at="2026-03-11T09:00:00.000000Z",
        note=json.dumps(
            {
                "kind": "batch_nlp",
                "source": "snapshot_backfill_cli",
                "doc_count": 12000,
                "first_doc_id": 1,
                "last_doc_id": 12000,
                "validation_scope": "bounded",
                "validated_doc_count": 12000,
            },
            sort_keys=True,
        ),
    )
    latest_run = ProcessorRun(
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
                "validation_scope": "limited",
                "validated_doc_count": 0,
            },
            sort_keys=True,
        ),
    )
    session.add_all([bounded_run, latest_run])
    session.commit()
    return int(project.project_id), int(bounded_run.run_id), int(latest_run.run_id)


def test_snapshot_readiness_service_reports_coverage_and_latest_run() -> None:
    db_path = _init_temp_db()
    _reset_db_service()
    DBService.initialize(db_path)
    db = DBService.get_instance()

    try:
        with db.get_session() as session:
            project_id, bounded_run_id, latest_run_id = _seed_snapshot_project(session)

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
        assert summary.latest_backfill_run_id == latest_run_id
        assert summary.latest_backfill_status == "ok"
        assert summary.latest_backfill_stage == "completed"
        assert summary.latest_backfill_last_doc_id == 2
        assert summary.contract_state == "bounded_validated"
        assert f"run #{bounded_run_id}" in (summary.contract_note or "")
        assert "Full-scale validation remains deferred" in (summary.contract_note or "")
        assert "Observational only" in (summary.summary_note or "")
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)


def test_snapshot_readiness_service_does_not_treat_small_run_as_bounded_validation() -> None:
    db_path = _init_temp_db()
    _reset_db_service()
    DBService.initialize(db_path)
    db = DBService.get_instance()

    try:
        with db.get_session() as session:
            project_id, _bounded_run_id, latest_run_id = _seed_snapshot_project(session)
            session.query(ProcessorRun).filter(ProcessorRun.run_id != latest_run_id).delete()
            session.commit()

        service = SnapshotReadinessService()
        with db.get_read_session() as session:
            summary = service.get_project_summary(session, project_id)

        assert summary.latest_backfill_run_id == latest_run_id
        assert summary.contract_state == "partial_coverage"
        assert "Full-scale validation remains deferred" not in (summary.contract_note or "")
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
            project_id, _bounded_run_id, _latest_run_id = _seed_snapshot_project(session)

        service = SnapshotReadinessService()
        with db.get_read_session() as session:
            session.commit = lambda: (_ for _ in ()).throw(AssertionError("commit should not be called"))
            summary = service.get_project_summary(session, project_id)

        assert summary.project_id == project_id
        assert summary.latest_backfill_status == "ok"
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)


def test_snapshot_readiness_service_reports_degraded_state_when_doc_stats_missing() -> None:
    db_path = _init_temp_db()
    _reset_db_service()
    DBService.initialize(db_path)
    db = DBService.get_instance()

    try:
        with db.get_session() as session:
            project_id, _bounded_run_id, _latest_run_id = _seed_snapshot_project(session)
            docs = session.query(SourceDocument).order_by(SourceDocument.doc_id.asc()).all()
            docs[1].snapshot_stats_state = "unknown"
            docs[1].snapshot_sentence_count = 0
            session.commit()

        service = SnapshotReadinessService()
        with db.get_read_session() as session:
            summary = service.get_project_summary(session, project_id)

        assert summary.contract_state == "stats_rebuild_required"
        assert summary.coverage_is_degraded is True
        assert summary.stats_valid_docs == 2
        assert summary.stats_unknown_docs == 1
        assert summary.stats_invalid_docs == 0
        assert "require rebuild or verification" in (summary.contract_note or "")
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)
