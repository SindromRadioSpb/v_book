from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from sqlalchemy import select

from app.infra.sa_models import DictProject, Library, ProcessorRun, RunError
from app.services.db_service import DBService
from app.services.project_telemetry_retention_service import (
    ProjectTelemetryRetentionService,
)


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


def _seed_project(session) -> int:
    library = Library(name="Telemetry")
    session.add(library)
    session.flush()
    project = DictProject(library_id=library.library_id, name="Telemetry Project")
    session.add(project)
    session.flush()

    for idx in range(8):
        session.add(
            ProcessorRun(
                project_id=project.project_id,
                engine="fake",
                engine_version="1",
                docs_total=1,
                docs_processed=1,
                status="ok",
                stage="completed",
                note=None,
            )
        )
    for idx in range(2):
        session.add(
            ProcessorRun(
                project_id=project.project_id,
                engine="fake",
                engine_version="1",
                docs_total=1,
                docs_processed=1,
                status="ok",
                stage="completed",
                note=f'{{"kind":"batch_nlp","marker":"{idx}"}}',
            )
        )
    for _ in range(2):
        session.add(
            ProcessorRun(
                project_id=project.project_id,
                engine="fake",
                engine_version="1",
                docs_total=1,
                docs_processed=1,
                status="ok",
                stage="completed",
                note=None,
            )
        )
    session.flush()

    failed_one = ProcessorRun(
        project_id=project.project_id,
        engine="fake",
        engine_version="1",
        docs_total=1,
        docs_processed=0,
        docs_failed=1,
        status="failed",
        stage="failed",
        error_message="boom",
    )
    failed_two = ProcessorRun(
        project_id=project.project_id,
        engine="fake",
        engine_version="1",
        docs_total=1,
        docs_processed=0,
        docs_failed=1,
        status="failed",
        stage="failed",
        error_message="boom2",
    )
    session.add_all([failed_one, failed_two])
    session.flush()
    session.add(RunError(run_id=failed_one.run_id, doc_id=None, stage="processing", message="e1"))
    session.add(RunError(run_id=failed_two.run_id, doc_id=None, stage="processing", message="e2"))
    session.commit()
    return int(project.project_id)


def test_build_summary_preserves_recent_ok_noted_ok_and_failed_rows() -> None:
    db_path = _init_temp_db()
    _reset_db_service()
    DBService.initialize(db_path)
    db = DBService.get_instance()
    service = ProjectTelemetryRetentionService()

    try:
        with db.get_session() as session:
            project_id = _seed_project(session)

        with db.get_read_session() as session:
            summary = service.build_summary(session, project_id, keep_latest_ok=2)

        assert summary.total_runs == 14
        assert summary.ok_runs == 12
        assert summary.non_ok_runs == 2
        assert summary.noted_ok_runs == 2
        assert summary.kept_recent_ok_runs == 2
        assert summary.prunable_ok_runs == 8
        assert summary.prunable_run_error_rows == 0
        assert summary.applied is False
        assert summary.oldest_prunable_run_id == 1
        assert summary.newest_prunable_run_id == 8
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)


def test_apply_retention_deletes_only_old_blank_success_rows() -> None:
    db_path = _init_temp_db()
    _reset_db_service()
    DBService.initialize(db_path)
    db = DBService.get_instance()
    service = ProjectTelemetryRetentionService()

    try:
        with db.get_session() as session:
            project_id = _seed_project(session)

        with db.get_session() as session:
            result = service.apply_retention(session, project_id, keep_latest_ok=2)
            session.commit()

        assert result.applied is True
        assert result.deleted_runs == 8
        assert result.deleted_run_errors == 0

        with db.get_read_session() as session:
            remaining_runs = (
                session.execute(
                    select(ProcessorRun)
                    .where(ProcessorRun.project_id == project_id)
                    .order_by(ProcessorRun.run_id)
                )
                .scalars()
                .all()
            )
            remaining_errors = session.execute(select(RunError)).scalars().all()

        assert len(remaining_runs) == 6
        assert len([run for run in remaining_runs if run.status == "failed"]) == 2
        assert (
            len([run for run in remaining_runs if run.status == "ok" and (run.note or "").strip()])
            == 2
        )
        assert (
            len(
                [
                    run
                    for run in remaining_runs
                    if run.status == "ok" and not (run.note or "").strip()
                ]
            )
            == 2
        )
        assert len(remaining_errors) == 2
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)
