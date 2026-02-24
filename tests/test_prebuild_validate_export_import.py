"""Regression tests for scripts/prebuild_validate.py export/import check."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import text

from app.services.db_service import DBService
from app.services.project_service import ProjectService
from scripts import prebuild_validate


def _reset_db_service() -> None:
    if DBService._instance:
        DBService.shutdown()
    DBService._instance = None
    DBService._db_manager = None


def test_check_export_import_allows_existing_fixed_name(tmp_path, monkeypatch):
    """check_export_import must not collide with existing '__EXPORT_TEST__'."""
    db_path = Path(tmp_path) / "prebuild_validate.db"

    _reset_db_service()
    db_service = DBService.initialize(db_path)
    project_service = ProjectService()

    with db_service.get_session() as session:
        library = project_service.get_or_create_default_library(session)
        project_service.create_project(
            session,
            name="__EXPORT_TEST__",
            description="Seed project to force old-name collision",
            library=library,
        )
        session.commit()

    _reset_db_service()

    class _FakeExportEngine:
        def export_project(self, project_id, out_path, options):  # noqa: D401
            _ = project_id, options
            Path(out_path).write_bytes(b"bundle")
            return SimpleNamespace(success=True, error_message="")

    class _FakeImportEngine:
        def import_project(self, bundle_path, options):  # noqa: D401
            _ = bundle_path, options
            return SimpleNamespace(success=True, error_message="", new_project_id=0)

    import app.services.project_exchange.export_engine as export_engine_module
    import app.services.project_exchange.import_engine as import_engine_module

    monkeypatch.setattr(export_engine_module, "ProjectExportEngine", _FakeExportEngine)
    monkeypatch.setattr(import_engine_module, "ProjectImportEngine", _FakeImportEngine)

    assert prebuild_validate.check_export_import(db_path) is True

    _reset_db_service()
    db_service = DBService.initialize(db_path)
    with db_service.get_session() as session:
        names = [
            row[0]
            for row in session.execute(
                text(
                    "SELECT name FROM dict_project "
                    "WHERE name LIKE '__EXPORT_TEST__%' ORDER BY name"
                )
            ).fetchall()
        ]

    # New per-run project names must be cleaned up; only the seed should remain.
    assert names == ["__EXPORT_TEST__"]

    _reset_db_service()
