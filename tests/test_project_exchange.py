"""Tests for project exchange (export/import bundles)."""

import json
import sqlite3
import tempfile
import zipfile
from pathlib import Path

import pytest

from app.services.db_service import DBService
from app.services.project_exchange import bundle_format
from app.services.project_exchange.constants import (
    BUNDLE_FORMAT_VERSION,
    MANIFEST_FILENAME,
    PAYLOAD_FILENAME,
    CHECKSUMS_FILENAME,
)
from app.services.project_exchange.dto import (
    ManifestInfo,
    ExportOptions,
    ImportOptions,
)
from app.services.project_exchange.export_engine import ProjectExportEngine
from app.services.project_exchange.import_engine import ProjectImportEngine


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def temp_db():
    """Create a temporary database with schema."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    # Apply all migrations
    migrations_dir = Path("app/infra/migrations")
    migration_files = sorted(migrations_dir.glob("*.sql"))

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        for migration_file in migration_files:
            with open(migration_file, "r", encoding="utf-8") as f:
                conn.executescript(f.read())
        conn.commit()
    finally:
        conn.close()

    DBService.initialize(str(db_path))
    yield db_path

    DBService._instance = None
    try:
        db_path.unlink()
    except (PermissionError, FileNotFoundError):
        pass


@pytest.fixture
def populated_project(temp_db):
    """Create a project with test data."""
    conn = sqlite3.connect(str(temp_db))
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        # Insert library
        conn.execute("INSERT INTO library (library_id, name) VALUES (1, 'Test Library')")

        # Insert project
        conn.execute("""
            INSERT INTO dict_project (project_id, library_id, name, src_lang, tgt_lang, nlp_engine)
            VALUES (1, 1, 'Test Project', 'he', 'ru', 'stanza')
        """)

        # Insert corpus
        conn.execute("""
            INSERT INTO source_corpus (corpus_id, project_id, name)
            VALUES (1, 1, 'Main Corpus')
        """)

        # Insert documents
        for i in range(3):
            doc_id = i + 1
            conn.execute("""
                INSERT INTO source_document (doc_id, corpus_id, file_path, file_name, file_ext, sha256, status)
                VALUES (?, 1, ?, ?, 'txt', ?, 'processed')
            """, (doc_id, f'/test/doc{doc_id}.txt', f'doc{doc_id}.txt', f'sha{doc_id:064d}'))

            conn.execute("""
                INSERT INTO document_text (doc_id, raw_text, ocr_used)
                VALUES (?, ?, 0)
            """, (doc_id, f'Test text {doc_id}'))

            # Insert sentences
            for j in range(5):
                sent_id = i * 5 + j + 1
                conn.execute("""
                    INSERT INTO document_sentence (sentence_id, doc_id, sent_index, text)
                    VALUES (?, ?, ?, ?)
                """, (sent_id, i+1, j, f"Sentence {sent_id}"))

        # Insert lemmas
        for i in range(10):
            conn.execute("""
                INSERT INTO lemma (lemma_id, project_id, lemma_text, pos)
                VALUES (?, 1, ?, 'NOUN')
            """, (i+1, f"lemma_{i+1}"))

        # Insert ngrams
        for i in range(5):
            conn.execute("""
                INSERT INTO ngram (ngram_id, project_id, n, surface_text, source_kind)
                VALUES (?, 1, 2, ?, 'ngram')
            """, (i+1, f"ngram_{i+1}"))

        conn.commit()
        return 1  # project_id

    finally:
        conn.close()


# ==============================================================================
# Unit Tests
# ==============================================================================


def test_manifest_roundtrip():
    """Test ManifestInfo serialization/deserialization."""
    manifest = ManifestInfo(
        bundle_format_version=1,
        app_version="1.0.0",
        schema_version=9,
        project_name="Test Project",
        project_src_lang="he",
        project_tgt_lang="ru",
        exported_at="2026-02-11T10:00:00Z",
        table_counts={"library": 1, "dict_project": 1, "lemma": 10},
    )

    # To dict
    data = manifest.to_dict()
    assert data["bundle_format_version"] == 1
    assert data["project_name"] == "Test Project"
    assert data["table_counts"]["lemma"] == 10

    # From dict
    manifest2 = ManifestInfo.from_dict(data)
    assert manifest2.bundle_format_version == manifest.bundle_format_version
    assert manifest2.project_name == manifest.project_name
    assert manifest2.table_counts == manifest.table_counts


def test_export_creates_valid_bundle(populated_project, temp_db):
    """Test export creates a bundle with correct structure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_path = Path(tmpdir) / "test_export.hdleproj"

        engine = ProjectExportEngine()
        report = engine.export_project(
            project_id=populated_project,
            out_path=bundle_path,
            options=ExportOptions(),
        )

        assert report.success
        assert bundle_path.exists()

        # Verify ZIP structure
        with zipfile.ZipFile(bundle_path, "r") as zf:
            names = set(zf.namelist())
            assert names == {MANIFEST_FILENAME, PAYLOAD_FILENAME, CHECKSUMS_FILENAME}

        # Verify manifest
        assert report.manifest.project_name == "Test Project"
        assert report.manifest.bundle_format_version == BUNDLE_FORMAT_VERSION


def test_checksum_validation_fails_on_tamper(populated_project, temp_db):
    """Test checksum validation detects tampering."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_path = Path(tmpdir) / "test_export.hdleproj"

        # Export
        engine = ProjectExportEngine()
        report = engine.export_project(
            project_id=populated_project,
            out_path=bundle_path,
            options=ExportOptions(),
        )
        assert report.success

        # Tamper with payload
        with zipfile.ZipFile(bundle_path, "a") as zf:
            zf.writestr(PAYLOAD_FILENAME, b"corrupted data")

        # Try to read
        extract_dir = Path(tmpdir) / "extract"
        extract_dir.mkdir()

        with pytest.raises(bundle_format.BundleFormatError, match="Checksum mismatch"):
            bundle_format.read_bundle(bundle_path, extract_dir)


def test_path_traversal_blocked():
    """Test path traversal attacks are blocked."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create malicious bundle
        bundle_path = Path(tmpdir) / "malicious.hdleproj"

        with zipfile.ZipFile(bundle_path, "w") as zf:
            zf.writestr(MANIFEST_FILENAME, "{}")
            zf.writestr(PAYLOAD_FILENAME, b"data")
            zf.writestr("../evil.txt", "malicious")
            zf.writestr(CHECKSUMS_FILENAME, "{}")

        extract_dir = Path(tmpdir) / "extract"
        extract_dir.mkdir()

        with pytest.raises(bundle_format.BundleFormatError, match="Invalid bundle structure"):
            bundle_format.read_bundle(bundle_path, extract_dir)


def test_schema_mismatch_rejected(temp_db):
    """Test import rejects bundles with incompatible schema version."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_path = Path(tmpdir) / "future_bundle.hdleproj"

        # Create fake bundle with future schema
        manifest = ManifestInfo(
            bundle_format_version=1,
            app_version="2.0.0",
            schema_version=999,  # Far future schema
            project_name="Future Project",
            project_src_lang="he",
            project_tgt_lang="ru",
            exported_at="2099-01-01T00:00:00Z",
            table_counts={},
        )

        # Create minimal valid payload
        payload_path = Path(tmpdir) / PAYLOAD_FILENAME
        conn = sqlite3.connect(str(payload_path))
        conn.execute("CREATE TABLE dummy (id INTEGER)")
        conn.close()

        bundle_format.create_bundle(payload_path, manifest, bundle_path)

        # Try to import
        engine = ProjectImportEngine()
        report = engine.import_project(
            bundle_path=bundle_path,
            options=ImportOptions(),
        )

        assert not report.success
        assert "schema" in report.error_message.lower()
        assert "999" in report.error_message


def test_export_excludes_credentials(populated_project, temp_db):
    """Test credentials table is not exported."""
    # Insert fake credential
    conn = sqlite3.connect(str(temp_db))
    conn.execute("""
        INSERT INTO credentials (key, encrypted_value, encryption_version)
        VALUES ('test_key', 'encrypted_secret', 1)
    """)
    conn.commit()
    conn.close()

    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_path = Path(tmpdir) / "test_export.hdleproj"

        engine = ProjectExportEngine()
        report = engine.export_project(
            project_id=populated_project,
            out_path=bundle_path,
            options=ExportOptions(),
        )

        assert report.success

        # Extract and check payload
        extract_dir = Path(tmpdir) / "extract"
        manifest, payload_path = bundle_format.read_bundle(bundle_path, extract_dir)

        # Verify credentials table is empty or doesn't exist
        payload_conn = sqlite3.connect(str(payload_path))
        try:
            result = payload_conn.execute("SELECT COUNT(*) FROM credentials").fetchone()
            assert result[0] == 0, "credentials table should be empty in payload"
        except sqlite3.OperationalError:
            # Table doesn't exist (acceptable)
            pass
        finally:
            payload_conn.close()


# ==============================================================================
# Integration Tests
# ==============================================================================


def test_export_import_roundtrip(populated_project, temp_db):
    """Test export->import roundtrip preserves data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_path = Path(tmpdir) / "test_bundle.hdleproj"

        # Export
        export_engine = ProjectExportEngine()
        export_report = export_engine.export_project(
            project_id=populated_project,
            out_path=bundle_path,
            options=ExportOptions(),
        )
        assert export_report.success

        # Import
        import_engine = ProjectImportEngine()
        import_report = import_engine.import_project(
            bundle_path=bundle_path,
            options=ImportOptions(custom_name="Test Project (Imported)"),
        )
        assert import_report.success

        # Verify counts match
        export_counts = export_report.manifest.table_counts
        import_counts = import_report.table_counts

        for table in ["library", "dict_project", "source_document", "lemma"]:
            assert import_counts.get(table, 0) == export_counts.get(table, 0), \
                f"Count mismatch for {table}"


def test_import_fk_integrity(populated_project, temp_db):
    """Test foreign key integrity after import."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_path = Path(tmpdir) / "test_bundle.hdleproj"

        # Export
        export_engine = ProjectExportEngine()
        export_report = export_engine.export_project(
            project_id=populated_project,
            out_path=bundle_path,
            options=ExportOptions(),
        )
        assert export_report.success

        # Import
        import_engine = ProjectImportEngine()
        import_report = import_engine.import_project(
            bundle_path=bundle_path,
            options=ImportOptions(custom_name="Test Project (FK Check)"),
        )
        assert import_report.success

        # Check FK integrity
        conn = sqlite3.connect(str(temp_db))
        conn.execute("PRAGMA foreign_key_check")
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        conn.close()

        assert len(violations) == 0, f"FK violations found: {violations}"


def test_import_name_conflict_rename(populated_project, temp_db):
    """Test auto-rename on name conflict."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_path = Path(tmpdir) / "test_bundle.hdleproj"

        # Export
        export_engine = ProjectExportEngine()
        export_report = export_engine.export_project(
            project_id=populated_project,
            out_path=bundle_path,
            options=ExportOptions(),
        )
        assert export_report.success

        # Import with same name (should auto-rename)
        import_engine = ProjectImportEngine()
        import_report = import_engine.import_project(
            bundle_path=bundle_path,
            options=ImportOptions(rename_if_conflict=True),
        )
        assert import_report.success

        # Check name was changed
        assert import_report.new_project_name != "Test Project"
        assert "imported" in import_report.new_project_name.lower()


# More integration tests would go here (FTS5 population, self-ref handling, etc.)
# Skipped for brevity - the structure follows the same pattern
