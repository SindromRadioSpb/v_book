from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import select

from app.infra.sa_models import DictProject, Library, ProcessorRun
from app.services.db_service import DBService


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


def _load_script_module():
    scripts_dir = str((Path(__file__).resolve().parent.parent / "scripts"))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import prune_project_telemetry

    return prune_project_telemetry


def _seed_project(db_path: Path) -> int:
    _reset_db_service()
    DBService.initialize(db_path)
    db = DBService.get_instance()
    try:
        with db.get_session() as session:
            library = Library(name="Telemetry")
            session.add(library)
            session.flush()
            project = DictProject(library_id=library.library_id, name="Telemetry Project")
            session.add(project)
            session.flush()
            for _ in range(6):
                session.add(
                    ProcessorRun(
                        project_id=project.project_id,
                        engine="fake",
                        engine_version="1",
                        docs_total=1,
                        docs_processed=1,
                        status="ok",
                        stage="completed",
                    )
                )
            session.add(
                ProcessorRun(
                    project_id=project.project_id,
                    engine="fake",
                    engine_version="1",
                    docs_total=1,
                    docs_processed=1,
                    status="ok",
                    stage="completed",
                    note='{"kind":"batch_nlp","marker":"keep"}',
                )
            )
            session.add(
                ProcessorRun(
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
            )
            session.commit()
            return int(project.project_id)
    finally:
        _reset_db_service()


def test_cli_dry_run_prints_summary_without_mutation(monkeypatch, capsys) -> None:
    db_path = _init_temp_db()
    try:
        project_id = _seed_project(db_path)
        module = _load_script_module()

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "prune_project_telemetry.py",
                "--db-path",
                str(db_path),
                "--project-id",
                str(project_id),
                "--keep-latest-ok",
                "2",
            ],
        )
        exit_code = module.main()
        assert exit_code == 0

        payload = json.loads(capsys.readouterr().out)
        assert payload["applied"] is False
        assert payload["prunable_ok_runs"] == 5

        _reset_db_service()
        DBService.initialize(db_path)
        with DBService.get_instance().get_read_session() as session:
            remaining = session.execute(
                select(ProcessorRun).where(ProcessorRun.project_id == project_id)
            ).scalars().all()
        assert len(remaining) == 8
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)


def test_cli_apply_requires_explicit_confirmation(monkeypatch) -> None:
    db_path = _init_temp_db()
    try:
        project_id = _seed_project(db_path)
        module = _load_script_module()

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "prune_project_telemetry.py",
                "--db-path",
                str(db_path),
                "--project-id",
                str(project_id),
                "--keep-latest-ok",
                "2",
                "--apply",
            ],
        )
        with pytest.raises(SystemExit):
            module.main()
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)


def test_cli_apply_prunes_old_blank_success_rows(monkeypatch, capsys) -> None:
    db_path = _init_temp_db()
    try:
        project_id = _seed_project(db_path)
        module = _load_script_module()

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "prune_project_telemetry.py",
                "--db-path",
                str(db_path),
                "--project-id",
                str(project_id),
                "--keep-latest-ok",
                "2",
                "--apply",
                "--confirm-project-id",
                str(project_id),
            ],
        )
        exit_code = module.main()
        assert exit_code == 0

        payload = json.loads(capsys.readouterr().out)
        assert payload["applied"] is True
        assert payload["deleted_runs"] == 5

        _reset_db_service()
        DBService.initialize(db_path)
        with DBService.get_instance().get_read_session() as session:
            remaining_runs = session.execute(
                select(ProcessorRun).where(ProcessorRun.project_id == project_id).order_by(ProcessorRun.run_id)
            ).scalars().all()

        assert len(remaining_runs) == 3
        assert len([run for run in remaining_runs if run.status == "failed"]) == 1
        assert len([run for run in remaining_runs if run.status == "ok" and (run.note or "").strip()]) == 1
        assert len([run for run in remaining_runs if run.status == "ok" and not (run.note or "").strip()]) == 1
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)
