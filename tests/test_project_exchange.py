"""Tests for project exchange (export/import bundles)."""

import json
import sqlite3
import tempfile
import zipfile
from pathlib import Path

import pytest
from sqlalchemy.orm import Session as SASession

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
from app.services.project_exchange import import_engine as import_engine_module
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
        conn.execute(
            """
            INSERT INTO dict_project (project_id, library_id, name, src_lang, tgt_lang, nlp_engine)
            VALUES (1, 1, 'Test Project', 'he', 'ru', 'stanza')
        """
        )

        # Insert corpus
        conn.execute(
            """
            INSERT INTO source_corpus (corpus_id, project_id, name)
            VALUES (1, 1, 'Main Corpus')
        """
        )

        # Insert documents
        for i in range(3):
            doc_id = i + 1
            conn.execute(
                """
                INSERT INTO source_document (doc_id, corpus_id, file_path, file_name, file_ext, sha256, status)
                VALUES (?, 1, ?, ?, 'txt', ?, 'processed')
            """,
                (doc_id, f"/test/doc{doc_id}.txt", f"doc{doc_id}.txt", f"sha{doc_id:064d}"),
            )

            conn.execute(
                """
                INSERT INTO document_text (doc_id, raw_text, ocr_used)
                VALUES (?, ?, 0)
            """,
                (doc_id, f"Test text {doc_id}"),
            )

            # Insert sentences
            for j in range(5):
                sent_id = i * 5 + j + 1
                conn.execute(
                    """
                    INSERT INTO document_sentence (sentence_id, doc_id, sent_index, text)
                    VALUES (?, ?, ?, ?)
                """,
                    (sent_id, i + 1, j, f"Sentence {sent_id}"),
                )

        # Insert lemmas
        for i in range(10):
            conn.execute(
                """
                INSERT INTO lemma (lemma_id, project_id, lemma_text, pos)
                VALUES (?, 1, ?, 'NOUN')
            """,
                (i + 1, f"lemma_{i+1}"),
            )

        # Insert ngrams
        for i in range(5):
            conn.execute(
                """
                INSERT INTO ngram (ngram_id, project_id, n, surface_text, source_kind)
                VALUES (?, 1, 2, ?, 'ngram')
            """,
                (i + 1, f"ngram_{i+1}"),
            )

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


def test_export_cancel_returns_cancelled_report(populated_project, tmp_path):
    """Cancel check should stop export quickly with a friendly report."""
    engine = ProjectExportEngine()
    out_path = tmp_path / "cancelled_export.hdleproj"
    report = engine.export_project(
        project_id=populated_project,
        out_path=out_path,
        options=ExportOptions(),
        cancel_check=lambda: True,
    )

    assert report.success is False
    assert "cancel" in (report.error_message or "").lower()
    assert not out_path.exists()


def test_export_fails_fast_when_source_db_corruption_probe_fails(
    populated_project, tmp_path, monkeypatch
):
    """Export must stop before payload creation if the source DB looks corrupt."""
    engine = ProjectExportEngine()
    out_path = tmp_path / "corrupt_export.hdleproj"
    payload_called = {"value": False}

    monkeypatch.setattr(
        engine,
        "_probe_host_db_corruption",
        lambda *_args, **_kwargs: {
            "ok": False,
            "quick_check_rows": ["database disk image is malformed"],
            "quick_check_error": "database disk image is malformed",
            "tm_entry_probe_ok": False,
            "tm_entry_probe_error": "database disk image is malformed",
        },
    )

    def _unexpected_payload(*args, **kwargs):
        payload_called["value"] = True
        raise AssertionError("_create_payload should not run for corrupt source DBs")

    monkeypatch.setattr(engine, "_create_payload", _unexpected_payload)

    report = engine.export_project(
        project_id=populated_project,
        out_path=out_path,
        options=ExportOptions(),
    )

    assert report.success is False
    assert payload_called["value"] is False
    assert "corrupted or unreadable" in (report.error_message or "").lower()
    assert "repair_db_corruption.py" in (report.error_message or "")
    assert not out_path.exists()


def test_import_cancel_returns_cancelled_report(populated_project, temp_db):
    """Cancel check should stop import quickly with a friendly report."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_path = Path(tmpdir) / "cancelled_import_bundle.hdleproj"
        export_engine = ProjectExportEngine()
        export_report = export_engine.export_project(
            project_id=populated_project,
            out_path=bundle_path,
            options=ExportOptions(),
        )
        assert export_report.success

        import_engine = ProjectImportEngine()
        report = import_engine.import_project(
            bundle_path=bundle_path,
            options=ImportOptions(custom_name="Cancelled Import"),
            cancel_check=lambda: True,
        )

    assert report.success is False
    assert "cancel" in (report.error_message or "").lower()


def test_import_rejects_duplicate_source_document_natural_keys(populated_project, temp_db):
    """Import should fail early with actionable error for duplicate (corpus_id, sha256) rows."""
    with tempfile.TemporaryDirectory() as tmpdir:
        payload_path = Path(tmpdir) / "duplicate_payload.db"
        bundle_path = Path(tmpdir) / "duplicate_docs_bundle.hdleproj"

        payload_conn = sqlite3.connect(str(payload_path))
        try:
            payload_conn.execute(
                """
                CREATE TABLE source_document (
                    doc_id INTEGER PRIMARY KEY,
                    corpus_id INTEGER NOT NULL,
                    file_path TEXT,
                    file_name TEXT,
                    file_ext TEXT,
                    sha256 TEXT,
                    status TEXT
                )
                """
            )
            payload_conn.executemany(
                """
                INSERT INTO source_document (doc_id, corpus_id, file_path, file_name, file_ext, sha256, status)
                VALUES (?, ?, ?, ?, 'txt', ?, 'ready')
                """,
                [
                    (1, 10, "/tmp/a.txt", "a.txt", "a" * 64),
                    (2, 10, "/tmp/b.txt", "b.txt", "a" * 64),
                ],
            )
            payload_conn.commit()
        finally:
            payload_conn.close()

        manifest = ManifestInfo(
            bundle_format_version=BUNDLE_FORMAT_VERSION,
            app_version="1.0.0",
            schema_version=35,
            project_name="Duplicate Docs Bundle",
            project_src_lang="he",
            project_tgt_lang="ru",
            exported_at="2026-03-08T00:00:00Z",
            table_counts={"source_document": 2},
        )
        bundle_format.create_bundle(payload_path, manifest, bundle_path)

        import_engine = ProjectImportEngine()
        report = import_engine.import_project(
            bundle_path=bundle_path,
            options=ImportOptions(custom_name="Duplicate Docs Import"),
        )

    assert report.success is False
    assert "duplicate source documents" in (report.error_message or "").lower()
    assert "(corpus_id, sha256)" in (report.error_message or "")


def test_import_cancel_after_partial_commit_cleans_rows(populated_project, temp_db, monkeypatch):
    """If cancel happens after early committed tables, cleanup must remove partial rows."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_path = Path(tmpdir) / "partial_cancel_import_bundle.hdleproj"
        export_engine = ProjectExportEngine()
        export_report = export_engine.export_project(
            project_id=populated_project,
            out_path=bundle_path,
            options=ExportOptions(),
        )
        assert export_report.success

        import_engine = ProjectImportEngine()
        cancel_state = {"value": False}
        call_counter = {"count": 0}
        original_import_table = import_engine._import_table

        def wrapped_import_table(*args, **kwargs):
            result = original_import_table(*args, **kwargs)
            call_counter["count"] += 1
            # library + dict_project are first two tables in insertion order.
            if call_counter["count"] >= 2:
                cancel_state["value"] = True
            return result

        monkeypatch.setattr(import_engine, "_import_table", wrapped_import_table)

        report = import_engine.import_project(
            bundle_path=bundle_path,
            options=ImportOptions(custom_name="Cancelled Import Partial"),
            cancel_check=lambda: bool(cancel_state["value"]),
        )

    assert report.success is False
    assert "cancel" in (report.error_message or "").lower()

    conn = sqlite3.connect(str(temp_db))
    try:
        project_count = conn.execute(
            "SELECT COUNT(*) FROM dict_project WHERE name = ?",
            ("Cancelled Import Partial",),
        ).fetchone()[0]
        library_count = conn.execute("SELECT COUNT(*) FROM library").fetchone()[0]
    finally:
        conn.close()

    assert project_count == 0
    # Fixture creates exactly one library row; partial-import cleanup must not leak extra rows.
    assert library_count == 1


def test_import_routes_write_phases_through_write_gate(populated_project, temp_db, monkeypatch):
    """Import should execute transactional write phases via shared write gate."""
    conn = sqlite3.connect(str(temp_db))
    try:
        # Force lemma batching during import.
        next_lemma_id = (
            conn.execute("SELECT COALESCE(MAX(lemma_id), 0) FROM lemma").fetchone()[0] + 1
        )
        conn.executemany(
            "INSERT INTO lemma (lemma_id, project_id, lemma_text, pos) VALUES (?, 1, ?, 'NOUN')",
            [(next_lemma_id + i, f"lemma_batch_{i:05d}") for i in range(1200)],
        )

        # Add enough documents so source_document import is split into multiple gate batches.
        next_doc_id = (
            conn.execute("SELECT COALESCE(MAX(doc_id), 0) FROM source_document").fetchone()[0] + 1
        )
        source_docs = []
        source_texts = []
        for i in range(600):
            doc_id = next_doc_id + i
            source_docs.append(
                (
                    doc_id,
                    f"/batch/doc_{doc_id}.txt",
                    f"doc_{doc_id}.txt",
                    f"sha{doc_id:064d}",
                )
            )
            source_texts.append((doc_id, f"Batch text {doc_id}"))
        conn.executemany(
            """
            INSERT INTO source_document (doc_id, corpus_id, file_path, file_name, file_ext, sha256, status)
            VALUES (?, 1, ?, ?, 'txt', ?, 'processed')
            """,
            source_docs,
        )
        conn.executemany(
            "INSERT INTO document_text (doc_id, raw_text, ocr_used) VALUES (?, ?, 0)",
            source_texts,
        )

        next_sentence_id = (
            conn.execute("SELECT COALESCE(MAX(sentence_id), 0) FROM document_sentence").fetchone()[
                0
            ]
            + 1
        )
        sentence_rows = []
        for i in range(600):
            sentence_id = next_sentence_id + i
            doc_id = 1 + (i % 3)
            sent_index = 1000 + i
            sentence_rows.append((sentence_id, doc_id, sent_index, f"Sentence batch {sentence_id}"))
        conn.executemany(
            """
            INSERT INTO document_sentence (sentence_id, doc_id, sent_index, text)
            VALUES (?, ?, ?, ?)
            """,
            sentence_rows,
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setenv("HDLE_IMPORT_LEMMA_BATCH_SIZE", "500")

    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_path = Path(tmpdir) / "write_gate_import_bundle.hdleproj"
        export_engine = ProjectExportEngine()
        export_report = export_engine.export_project(
            project_id=populated_project,
            out_path=bundle_path,
            options=ExportOptions(),
        )
        assert export_report.success

        operations: list[str] = []

        def fake_run_serialized_db_write(operation, callback, **_kwargs):
            operations.append(str(operation))
            return callback()

        monkeypatch.setattr(
            import_engine_module,
            "run_serialized_db_write",
            fake_run_serialized_db_write,
        )

        import_engine = ProjectImportEngine()
        report = import_engine.import_project(
            bundle_path=bundle_path,
            options=ImportOptions(custom_name="Write Gate Import"),
        )

    assert report.success
    assert "import.ensure_fts" in operations
    assert any(op.startswith("import.table.") for op in operations)
    assert "import.fix_general_corpus_self_ref" in operations
    lemma_ops = [op for op in operations if op == "import.table.lemma"]
    source_document_ops = [op for op in operations if op == "import.table.source_document"]
    document_sentence_ops = [op for op in operations if op == "import.table.document_sentence"]
    assert len(lemma_ops) >= 3
    assert len(source_document_ops) >= 2
    assert len(document_sentence_ops) >= 3


def test_import_cancel_during_lemma_batch_cleans_rows(populated_project, temp_db, monkeypatch):
    """Cancel during lemma batching should return cancelled report and cleanup imported rows."""
    conn = sqlite3.connect(str(temp_db))
    try:
        next_lemma_id = (
            conn.execute("SELECT COALESCE(MAX(lemma_id), 0) FROM lemma").fetchone()[0] + 1
        )
        conn.executemany(
            "INSERT INTO lemma (lemma_id, project_id, lemma_text, pos) VALUES (?, 1, ?, 'NOUN')",
            [(next_lemma_id + i, f"lemma_cancel_{i:05d}") for i in range(1200)],
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setenv("HDLE_IMPORT_LEMMA_BATCH_SIZE", "500")

    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_path = Path(tmpdir) / "lemma_cancel_bundle.hdleproj"
        export_engine = ProjectExportEngine()
        export_report = export_engine.export_project(
            project_id=populated_project,
            out_path=bundle_path,
            options=ExportOptions(),
        )
        assert export_report.success

        import_engine = ProjectImportEngine()
        cancel_state = {"value": False}
        lemma_batches = {"count": 0}

        def fake_run_serialized_db_write(operation, callback, **_kwargs):
            result = callback()
            if operation == "import.table.lemma":
                lemma_batches["count"] += 1
                if lemma_batches["count"] == 1:
                    cancel_state["value"] = True
            return result

        monkeypatch.setattr(
            import_engine_module,
            "run_serialized_db_write",
            fake_run_serialized_db_write,
        )

        report = import_engine.import_project(
            bundle_path=bundle_path,
            options=ImportOptions(custom_name="Cancelled During Lemma Batches"),
            cancel_check=lambda: bool(cancel_state["value"]),
        )

    assert report.success is False
    assert "cancel" in (report.error_message or "").lower()
    assert lemma_batches["count"] >= 1

    conn = sqlite3.connect(str(temp_db))
    try:
        project_count = conn.execute(
            "SELECT COUNT(*) FROM dict_project WHERE name = ?",
            ("Cancelled During Lemma Batches",),
        ).fetchone()[0]
        library_count = conn.execute("SELECT COUNT(*) FROM library").fetchone()[0]
    finally:
        conn.close()

    assert project_count == 0
    assert library_count == 1


def test_import_cancel_during_document_sentence_batch_cleans_rows(
    populated_project,
    temp_db,
    monkeypatch,
):
    """Cancel during generic batched table import should cleanup imported rows."""
    conn = sqlite3.connect(str(temp_db))
    try:
        next_sentence_id = (
            conn.execute("SELECT COALESCE(MAX(sentence_id), 0) FROM document_sentence").fetchone()[
                0
            ]
            + 1
        )
        sentence_rows = []
        for i in range(600):
            sentence_id = next_sentence_id + i
            doc_id = 1 + (i % 3)
            sent_index = 1000 + i
            sentence_rows.append(
                (sentence_id, doc_id, sent_index, f"Sentence cancel {sentence_id}")
            )
        conn.executemany(
            """
            INSERT INTO document_sentence (sentence_id, doc_id, sent_index, text)
            VALUES (?, ?, ?, ?)
            """,
            sentence_rows,
        )
        conn.commit()
    finally:
        conn.close()

    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_path = Path(tmpdir) / "document_sentence_cancel_bundle.hdleproj"
        export_engine = ProjectExportEngine()
        export_report = export_engine.export_project(
            project_id=populated_project,
            out_path=bundle_path,
            options=ExportOptions(),
        )
        assert export_report.success

        import_engine = ProjectImportEngine()
        cancel_state = {"value": False}
        sentence_batches = {"count": 0}

        def fake_run_serialized_db_write(operation, callback, **_kwargs):
            result = callback()
            if operation == "import.table.document_sentence":
                sentence_batches["count"] += 1
                if sentence_batches["count"] == 1:
                    cancel_state["value"] = True
            return result

        monkeypatch.setattr(
            import_engine_module,
            "run_serialized_db_write",
            fake_run_serialized_db_write,
        )

        report = import_engine.import_project(
            bundle_path=bundle_path,
            options=ImportOptions(custom_name="Cancelled During Sentence Batches"),
            cancel_check=lambda: bool(cancel_state["value"]),
        )

    assert report.success is False
    assert "cancel" in (report.error_message or "").lower()
    assert sentence_batches["count"] >= 1

    conn = sqlite3.connect(str(temp_db))
    try:
        project_count = conn.execute(
            "SELECT COUNT(*) FROM dict_project WHERE name = ?",
            ("Cancelled During Sentence Batches",),
        ).fetchone()[0]
        library_count = conn.execute("SELECT COUNT(*) FROM library").fetchone()[0]
    finally:
        conn.close()

    assert project_count == 0
    assert library_count == 1


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


def test_create_bundle_cleans_partial_output_on_failure(tmp_path, monkeypatch):
    payload_path = tmp_path / PAYLOAD_FILENAME
    conn = sqlite3.connect(str(payload_path))
    conn.execute("CREATE TABLE dummy (id INTEGER PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO dummy (value) VALUES ('ok')")
    conn.commit()
    conn.close()

    bundle_path = tmp_path / "broken_bundle.hdleproj"
    manifest = ManifestInfo(
        bundle_format_version=1,
        app_version="1.0.0",
        schema_version=52,
        project_name="Broken Bundle",
        project_src_lang="he",
        project_tgt_lang="ru",
        exported_at="2026-03-29T00:00:00Z",
        table_counts={"dummy": 1},
    )

    original_write = zipfile.ZipFile.write

    def _crash_on_payload(self, filename, arcname=None, *args, **kwargs):
        if Path(str(filename)).name == PAYLOAD_FILENAME:
            raise RuntimeError("simulated payload write crash")
        return original_write(self, filename, arcname, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "write", _crash_on_payload)

    with pytest.raises(bundle_format.BundleFormatError, match="simulated payload write crash"):
        bundle_format.create_bundle(payload_path, manifest, bundle_path)

    assert bundle_path.exists() is False
    assert (tmp_path / "broken_bundle.hdleproj.partial").exists() is False


def test_create_bundle_reports_final_stage_progress(tmp_path):
    payload_path = tmp_path / PAYLOAD_FILENAME
    conn = sqlite3.connect(str(payload_path))
    conn.execute("CREATE TABLE dummy (id INTEGER PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO dummy (value) VALUES ('ok')")
    conn.commit()
    conn.close()

    bundle_path = tmp_path / "progress_bundle.hdleproj"
    manifest = ManifestInfo(
        bundle_format_version=1,
        app_version="1.0.0",
        schema_version=52,
        project_name="Progress Bundle",
        project_src_lang="he",
        project_tgt_lang="ru",
        exported_at="2026-03-29T00:00:00Z",
        table_counts={"dummy": 1},
    )

    events: list[tuple[str, int, int]] = []
    bundle_format.create_bundle(
        payload_path,
        manifest,
        bundle_path,
        progress_callback=lambda stage, current, total: events.append((stage, current, total)),
    )

    assert bundle_path.exists() is True
    assert events
    assert events[0][0] == "Computing checksums..."
    assert events[-1][0] == "Finalizing bundle..."
    assert events[-1][1:] == (6, 6)


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
    conn.execute(
        """
        INSERT INTO credentials (key, encrypted_value, encryption_version)
        VALUES ('test_key', 'encrypted_secret', 1)
    """
    )
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


def test_export_creates_payload_schema_including_document_sentence(populated_project, temp_db):
    """Regression test: ensure document_sentence table exists in payload DB.

    This test catches the bug where export_engine.py used a relative path
    for migrations that failed in PyInstaller builds, causing the payload
    DB to have no schema, leading to "no such table: main.document_sentence".
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_path = Path(tmpdir) / "test_export.hdleproj"

        engine = ProjectExportEngine()
        report = engine.export_project(
            project_id=populated_project,
            out_path=bundle_path,
            options=ExportOptions(),
        )

        assert report.success, f"Export failed: {report.error_message}"

        # Extract bundle
        extract_dir = Path(tmpdir) / "extract"
        manifest, payload_path = bundle_format.read_bundle(bundle_path, extract_dir)

        # Verify document_sentence table exists and has data
        payload_conn = sqlite3.connect(str(payload_path))
        try:
            # Check table exists
            result = payload_conn.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='document_sentence'
            """
            ).fetchone()
            assert result is not None, "document_sentence table missing from payload"
            assert result[0] == "document_sentence"

            # Check data was exported
            result = payload_conn.execute("SELECT COUNT(*) FROM document_sentence").fetchone()
            assert result[0] > 0, "document_sentence should contain exported data"

            # Verify it matches expected count (3 docs × 5 sentences = 15)
            assert result[0] == 15, f"Expected 15 sentences, got {result[0]}"

        finally:
            payload_conn.close()


def test_pronunciation_sidecar_export_chunks_in_clause(populated_project, temp_db, monkeypatch):
    """Regression: pronunciation sidecar export must chunk large IN-clause lookups."""
    total_norms = 240

    conn = sqlite3.connect(str(temp_db))
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        for i in range(total_norms):
            lemma_id = 10_000 + i
            norm = f"norm_{i:05d}"
            conn.execute(
                """
                INSERT INTO lemma (lemma_id, project_id, lemma_text, pos, norm_text)
                VALUES (?, 1, ?, 'NOUN', ?)
                """,
                (lemma_id, f"lemma_chunk_{i:05d}", norm),
            )
            conn.execute(
                """
                INSERT INTO pronunciation_entry (lang, src_norm, niqqud_text, source, is_override)
                VALUES ('he', ?, ?, 'manual', 1)
                """,
                (norm, f"niqqud_{i:05d}"),
            )
        conn.commit()
    finally:
        conn.close()

    engine = ProjectExportEngine()
    monkeypatch.setattr(engine, "_resolve_sqlite_max_variables", lambda session: 32)

    original_execute = SASession.execute

    def guarded_execute(self, statement, *args, **kwargs):
        params = statement.compile().params
        norms_param = params.get("src_norm_1")
        if isinstance(norms_param, list):
            assert len(norms_param) <= 31, "IN-clause chunk exceeded forced variable limit"
        return original_execute(self, statement, *args, **kwargs)

    monkeypatch.setattr(SASession, "execute", guarded_execute)

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "pronunciation_metadata.tsv"
        exported = engine._export_pronunciation_metadata(populated_project, out_path)

        assert exported == total_norms
        content = out_path.read_text(encoding="utf-8").splitlines()
        assert len(content) == total_norms + 1  # header + rows
        assert content[0].startswith("lang\tsrc_norm\t")


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
            assert import_counts.get(table, 0) == export_counts.get(
                table, 0
            ), f"Count mismatch for {table}"


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


def test_export_filters_orphan_lemma_doc_stat_rows(populated_project, temp_db):
    """Export must skip orphan lemma_doc_stat rows to keep payload importable."""
    conn = sqlite3.connect(str(temp_db))
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        # Valid row (lemma_id=1 exists in fixture).
        conn.execute(
            """
            INSERT INTO lemma_doc_stat (project_id, doc_id, lemma_id, freq_abs, sample_sentence_id)
            VALUES (1, 1, 1, 2, 1)
            """
        )
        # Orphan row (lemma_id does not exist) must be filtered out by export.
        conn.execute(
            """
            INSERT INTO lemma_doc_stat (project_id, doc_id, lemma_id, freq_abs, sample_sentence_id)
            VALUES (1, 1, 999999, 1, 1)
            """
        )
        conn.commit()
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.close()

    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_path = Path(tmpdir) / "orphan_filter_bundle.hdleproj"

        export_engine = ProjectExportEngine()
        export_report = export_engine.export_project(
            project_id=populated_project,
            out_path=bundle_path,
            options=ExportOptions(),
        )
        assert export_report.success

        extract_dir = Path(tmpdir) / "extract"
        _manifest, payload_path = bundle_format.read_bundle(bundle_path, extract_dir)
        payload_conn = sqlite3.connect(str(payload_path))
        try:
            count = payload_conn.execute("SELECT COUNT(*) FROM lemma_doc_stat").fetchone()[0]
            max_lemma = payload_conn.execute("SELECT MAX(lemma_id) FROM lemma_doc_stat").fetchone()[
                0
            ]
            assert count == 1
            assert max_lemma == 1
        finally:
            payload_conn.close()


def test_export_import_roundtrip_preserves_tm_global_link(populated_project, temp_db):
    """tm_global rows referenced by project TM entries must roundtrip with remapped IDs."""
    conn = sqlite3.connect(str(temp_db))
    try:
        conn.execute(
            """
            INSERT INTO tm_global (
                tm_global_id, src_lang, tgt_lang, kind, src_norm, src_text,
                translation, status, origin, confidence, is_noise, noise_reason,
                notes, source_tm_id, created_at, updated_at
            )
            VALUES (
                2001, 'he', 'ru', 'lemma', 'lemma_1', 'lemma_1',
                'перевод', 'approved', 'import', NULL, 0, NULL,
                'seed', NULL, '2026-02-26T00:00:00Z', '2026-02-26T00:00:00Z'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO tm_entry (
                tm_id, project_id, kind, src_lang, tgt_lang, src_text, src_norm,
                translation, translation_norm, pos, domain, notes, status, confidence,
                origin, source_ref, created_at, updated_at, approved_at, approved_by,
                is_noise, noise_reason, norm_text, lemma_id, cluster_id, ngram_id, tm_global_id
            )
            VALUES (
                3001, 1, 'lemma', 'he', 'ru', 'lemma_1', 'lemma_1',
                'перевод', NULL, NULL, NULL, NULL, 'approved', NULL,
                'import', 'test_tm_global_roundtrip', '2026-02-26T00:00:00Z',
                '2026-02-26T00:00:00Z', NULL, NULL, 0, NULL, 'lemma_1', 1, NULL, NULL, 2001
            )
            """
        )
        conn.commit()
    finally:
        conn.close()

    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_path = Path(tmpdir) / "tm_global_bundle.hdleproj"

        export_engine = ProjectExportEngine()
        export_report = export_engine.export_project(
            project_id=populated_project,
            out_path=bundle_path,
            options=ExportOptions(),
        )
        assert export_report.success
        assert export_report.manifest.table_counts.get("tm_global", 0) >= 1

        import_engine = ProjectImportEngine()
        import_report = import_engine.import_project(
            bundle_path=bundle_path,
            options=ImportOptions(custom_name="Test Project (TM Global Imported)"),
        )
        assert import_report.success
        assert import_report.new_project_id is not None
        assert import_report.table_counts.get("tm_global", 0) >= 1

        conn = sqlite3.connect(str(temp_db))
        try:
            row = conn.execute(
                """
                SELECT te.project_id, te.lemma_id, l.project_id, te.tm_global_id, tg.tm_global_id
                FROM tm_entry te
                LEFT JOIN lemma l ON l.lemma_id = te.lemma_id
                LEFT JOIN tm_global tg ON tg.tm_global_id = te.tm_global_id
                WHERE te.project_id = ? AND te.source_ref = 'test_tm_global_roundtrip'
                """,
                (import_report.new_project_id,),
            ).fetchone()
            assert row is not None
            (
                imported_project_id,
                imported_lemma_id,
                lemma_project_id,
                imported_global_id,
                resolved_global_id,
            ) = row
            assert imported_project_id == import_report.new_project_id
            assert imported_lemma_id is not None
            assert lemma_project_id == import_report.new_project_id
            assert imported_global_id is not None
            assert resolved_global_id == imported_global_id
        finally:
            conn.close()


def test_export_filters_cross_project_sample_sentence_refs(populated_project, temp_db):
    """Export must drop sample_sentence references that point to another project."""
    conn = sqlite3.connect(str(temp_db))
    try:
        conn.execute(
            """
            INSERT INTO dict_project (project_id, library_id, name, src_lang, tgt_lang, nlp_engine)
            VALUES (2, 1, 'Other Project', 'he', 'ru', 'stanza')
            """
        )
        conn.execute(
            """
            INSERT INTO source_corpus (corpus_id, project_id, name)
            VALUES (2, 2, 'Other Corpus')
            """
        )
        conn.execute(
            """
            INSERT INTO source_document (doc_id, corpus_id, file_path, file_name, file_ext, sha256, status)
            VALUES (101, 2, '/test/other.txt', 'other.txt', 'txt', ?, 'processed')
            """,
            ("b" * 64,),
        )
        conn.execute(
            """
            INSERT INTO document_sentence (sentence_id, doc_id, sent_index, text)
            VALUES (101, 101, 0, 'Other project sentence')
            """
        )
        conn.execute(
            """
            INSERT INTO lemma_project_stat (project_id, lemma_id, freq_abs, sample_sentence_id)
            VALUES (1, 1, 10, 1)
            """
        )
        conn.execute(
            """
            INSERT INTO lemma_project_stat (project_id, lemma_id, freq_abs, sample_sentence_id)
            VALUES (1, 2, 5, 101)
            """
        )
        conn.commit()
    finally:
        conn.close()

    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_path = Path(tmpdir) / "sample_sentence_filter_bundle.hdleproj"

        export_engine = ProjectExportEngine()
        export_report = export_engine.export_project(
            project_id=populated_project,
            out_path=bundle_path,
            options=ExportOptions(),
        )
        assert export_report.success

        extract_dir = Path(tmpdir) / "extract"
        _manifest, payload_path = bundle_format.read_bundle(bundle_path, extract_dir)
        payload_conn = sqlite3.connect(str(payload_path))
        try:
            rows = payload_conn.execute(
                """
                SELECT lemma_id, sample_sentence_id
                FROM lemma_project_stat
                ORDER BY lemma_id
                """
            ).fetchall()
            assert rows == [(1, 1)]
        finally:
            payload_conn.close()


# More integration tests would go here (FTS5 population, self-ref handling, etc.)
# Skipped for brevity - the structure follows the same pattern
