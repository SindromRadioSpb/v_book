"""Tests for read-only project import preflight summaries."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from app.services.db_service import DBService
from app.services.project_exchange.bundle_format import create_bundle
from app.services.project_exchange.dto import ImportOptions, ManifestInfo
from app.services.project_exchange.import_engine import ProjectImportEngine


def _create_host_db(path: Path, schema_version: int, project_name: str | None = None) -> Path:
    migrations_dir = Path("app/infra/migrations")
    migration_files = sorted(migrations_dir.glob("*.sql"))

    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        for migration_file in migration_files:
            conn.executescript(migration_file.read_text(encoding="utf-8"))
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('schema_version', ?)",
            (str(schema_version),),
        )
        conn.execute("INSERT INTO library (library_id, name) VALUES (1, 'Library')")
        if project_name:
            conn.execute(
                """
                INSERT INTO dict_project (project_id, library_id, name, src_lang, tgt_lang, nlp_engine)
                VALUES (1, 1, ?, 'he', 'en', 'stanza')
                """,
                (project_name,),
            )
        conn.commit()
    finally:
        conn.close()
    return path


def _create_payload_db(path: Path) -> Path:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE payload_marker (id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO payload_marker (value) VALUES ('ok')")
        conn.commit()
    finally:
        conn.close()
    return path


@pytest.fixture
def temp_host_db(tmp_path):
    db_path = _create_host_db(
        tmp_path / "host.db", schema_version=65, project_name="Existing Project"
    )
    DBService.initialize(str(db_path))
    yield db_path
    DBService.shutdown()
    DBService._instance = None
    DBService._db_manager = None


def test_preflight_import_reports_name_conflict_and_final_name(temp_host_db, tmp_path):
    payload_path = _create_payload_db(tmp_path / "payload.db")
    bundle_path = tmp_path / "bundle.hdleproj"
    manifest = ManifestInfo(
        bundle_format_version=1,
        app_version="1.0.0",
        schema_version=65,
        project_name="Existing Project",
        project_src_lang="he",
        project_tgt_lang="en",
        exported_at="2026-03-14T10:00:00Z",
        table_counts={"source_document": 2, "document_sentence": 5},
        pronunciation_metadata_count=3,
    )
    create_bundle(payload_path, manifest, bundle_path)

    report = ProjectImportEngine().preflight_import(
        bundle_path, ImportOptions(rename_if_conflict=True)
    )

    assert report.host_schema_version == 65
    assert report.name_conflict is True
    assert report.original_project_name == "Existing Project"
    assert report.final_project_name.startswith("Existing Project (imported ")
    assert report.total_rows == 7
    assert report.warnings
    assert "already exists" in report.warnings[0]


def test_preflight_import_rejects_newer_bundle_schema(temp_host_db, tmp_path):
    payload_path = _create_payload_db(tmp_path / "payload_newer.db")
    bundle_path = tmp_path / "bundle_newer.hdleproj"
    manifest = ManifestInfo(
        bundle_format_version=1,
        app_version="1.0.0",
        schema_version=999,
        project_name="Future Project",
        project_src_lang="he",
        project_tgt_lang="en",
        exported_at="2026-03-14T10:00:00Z",
        table_counts={"source_document": 1},
    )
    create_bundle(payload_path, manifest, bundle_path)

    with pytest.raises(ValueError, match="Bundle requires schema v999"):
        ProjectImportEngine().preflight_import(bundle_path, ImportOptions())
