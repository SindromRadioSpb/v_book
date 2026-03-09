"""Tests for Task 12: FTS5 + NLP Pipeline + Crash Recovery Fix.

These are smoke tests to verify code compiles and basic logic is correct.
Full integration testing requires manual UI testing with real database.
"""

import pytest
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock


class TestCodeImports:
    """Test that all modified modules import successfully."""

    def test_db_manager_imports(self):
        """Test DatabaseManager with _ensure_fts_health method."""
        from app.infra.db import DatabaseManager

        # Verify method exists
        assert hasattr(DatabaseManager, '_ensure_fts_health'), \
            "DatabaseManager should have _ensure_fts_health method"
        assert hasattr(DatabaseManager, 'apply_migrations'), \
            "DatabaseManager should have apply_migrations method"

    def test_fts_manager_imports(self):
        """Test FTS manager functions."""
        from app.infra.fts_manager import ensure_fts_tables, check_fts_exists

        # Verify functions exist
        assert callable(ensure_fts_tables), "ensure_fts_tables should be callable"
        assert callable(check_fts_exists), "check_fts_exists should be callable"

    def test_process_service_imports(self):
        """Test ProcessService with rollback fixes."""
        from app.services.process_service import ProcessService

        # Verify class exists and has process_document method
        assert hasattr(ProcessService, 'process_document'), \
            "ProcessService should have process_document method"

    def test_workers_import(self):
        """Test ProcessWorker staged/batch signals exist."""
        from app.ui.workers import ProcessWorker

        # Verify class exists
        assert hasattr(ProcessWorker, 'run'), "ProcessWorker should have run method"
        assert hasattr(ProcessWorker, 'state_changed'), "ProcessWorker should expose structured state"
        assert hasattr(ProcessWorker, 'pause'), "ProcessWorker should support pause"
        assert hasattr(ProcessWorker, 'resume'), "ProcessWorker should support resume"
        assert hasattr(ProcessWorker, 'cancel'), "ProcessWorker should support cancel"


class TestFTSManagerBasics:
    """Test FTS manager basic functionality."""

    def test_check_fts_exists_on_empty_db(self):
        """Test check_fts_exists returns False on empty database."""
        from app.infra.fts_manager import check_fts_exists

        # Create in-memory database
        conn = sqlite3.connect(":memory:")
        try:
            sentence_exists, term_exists = check_fts_exists(conn, schema="main")

            # Empty DB should have no FTS tables
            assert sentence_exists == False, "Empty DB should not have sentence_fts"
            assert term_exists == False, "Empty DB should not have term_fts"
        finally:
            conn.close()

    def test_ensure_fts_creates_tables(self):
        """Test ensure_fts_tables creates FTS tables when missing."""
        from app.infra.fts_manager import ensure_fts_tables, check_fts_exists

        # Create in-memory database with base tables
        conn = sqlite3.connect(":memory:")
        try:
            # Create base tables
            conn.execute("""
                CREATE TABLE document_sentence (
                    sentence_id INTEGER PRIMARY KEY,
                    doc_id INTEGER NOT NULL,
                    sent_index INTEGER NOT NULL,
                    text TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE term_search (
                    term_rowid INTEGER PRIMARY KEY,
                    he_term TEXT NOT NULL,
                    ru_translation TEXT,
                    notes TEXT,
                    project_id INTEGER,
                    kind TEXT,
                    lemma_id INTEGER,
                    ngram_id INTEGER
                )
            """)
            conn.commit()

            # Ensure FTS tables
            result = ensure_fts_tables(conn, schema="main", rebuild=False)

            # Should report tables were created
            assert result.get("sentence_fts") == True, "sentence_fts should be created"
            assert result.get("term_fts") == True, "term_fts should be created"

            # Verify tables exist
            sentence_exists, term_exists = check_fts_exists(conn, schema="main")
            assert sentence_exists == True, "sentence_fts should exist after ensure_fts_tables"
            assert term_exists == True, "term_fts should exist after ensure_fts_tables"

        finally:
            conn.close()


class TestProcessRollbackPattern:
    """Test rollback pattern in exception handler."""

    def test_rollback_on_error_pattern(self):
        """Verify the rollback pattern in process_service exception handler.

        This test doesn't run the actual code, just verifies the pattern exists.
        """
        from app.services.process_service import ProcessService
        import inspect

        # Get process_document source
        source = inspect.getsource(ProcessService.process_document)

        # Verify critical patterns exist in code
        assert "session.rollback()" in source, \
            "process_document should call session.rollback() on error"
        assert "run_id = run.run_id" in source, \
            "process_document should save run_id before try block"
        assert "session.get(ProcessorRun, run_id)" in source, \
            "process_document should re-fetch run using saved run_id"


class TestWorkerBatchContract:
    """Test staged batch routing in ProcessWorker."""

    def test_process_worker_uses_batch_service(self):
        """Verify ProcessWorker routes through process_documents_batch()."""
        from app.ui.workers import ProcessWorker
        import inspect

        # Get run method source
        source = inspect.getsource(ProcessWorker.run)

        assert "process_documents_batch(" in source, \
            "ProcessWorker should route through ProcessService.process_documents_batch"
        assert "resume_latest=True" in source, \
            "ProcessWorker should auto-resume the latest matching batch run"
        assert "state_callback=lambda state: self._on_state_changed(state, last_state)" in source, \
            "ProcessWorker should forward structured state from the batch service"


class TestDiagnosticScript:
    """Test diagnostic script exists and is runnable."""

    def test_diag_script_exists(self):
        """Test that diag_db_health.py exists."""
        script_path = Path("scripts/diag_db_health.py")
        assert script_path.exists(), f"Diagnostic script should exist at {script_path}"

    def test_diag_script_has_checker(self):
        """Test that diag script has DBHealthChecker class."""
        import sys
        sys.path.insert(0, str(Path("scripts")))

        try:
            from diag_db_health import DBHealthChecker
            assert hasattr(DBHealthChecker, 'check_all'), \
                "DBHealthChecker should have check_all method"
        finally:
            sys.path.pop(0)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
