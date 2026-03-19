"""Tests for FTS5 self-healing functionality.

Verifies that FTS tables are automatically created when missing,
preventing "no such table: sentence_fts" errors.
"""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from app.infra.db import DatabaseManager
from app.infra.fts_manager import ensure_fts_tables, check_fts_exists


class TestFTSSelfHealing:
    """Test FTS5 self-healing and consistency checks."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        yield db_path
        if db_path.exists():
            db_path.unlink()

    def test_fts_presence_after_migrations(self, temp_db):
        """Test that FTS tables exist after applying migrations."""
        # Apply migrations
        db_manager = DatabaseManager(temp_db)
        db_manager.apply_migrations()

        # Check FTS tables exist
        conn = sqlite3.connect(str(temp_db))
        try:
            sentence_fts_exists, term_fts_exists = check_fts_exists(conn)
            assert sentence_fts_exists, "sentence_fts should exist after migrations"
            assert term_fts_exists, "term_fts should exist after migrations"
        finally:
            conn.close()
            db_manager.close()

    def test_ensure_fts_creates_missing_tables(self, temp_db):
        """Test that ensure_fts_tables creates missing FTS tables."""
        # Create DB with schema but without FTS tables
        db_manager = DatabaseManager(temp_db)
        db_manager.apply_migrations()

        conn = sqlite3.connect(str(temp_db))
        try:
            # Deliberately drop FTS tables to simulate the bug
            conn.execute("DROP TABLE IF EXISTS sentence_fts")
            conn.execute("DROP TABLE IF EXISTS term_fts")
            conn.commit()

            # Verify they're gone
            sentence_fts_exists, term_fts_exists = check_fts_exists(conn)
            assert not sentence_fts_exists, "sentence_fts should be missing"
            assert not term_fts_exists, "term_fts should be missing"

            # Run ensure_fts_tables
            results = ensure_fts_tables(conn, schema="main", rebuild=False)

            # Verify they were created
            assert results["sentence_fts"] is True, "sentence_fts should be created"
            assert results["term_fts"] is True, "term_fts should be created"

            # Verify they exist now
            sentence_fts_exists, term_fts_exists = check_fts_exists(conn)
            assert sentence_fts_exists, "sentence_fts should exist after ensure"
            assert term_fts_exists, "term_fts should exist after ensure"

        finally:
            conn.close()
            db_manager.close()

    def test_ensure_fts_with_rebuild(self, temp_db):
        """Test that ensure_fts_tables rebuilds FTS data when requested."""
        db_manager = DatabaseManager(temp_db)
        db_manager.apply_migrations()

        conn = sqlite3.connect(str(temp_db))
        try:
            # Insert some test data
            conn.execute(
                "INSERT INTO dict_project (project_id, library_id, name) VALUES (1, 1, 'Test Project')"
            )
            conn.execute("INSERT INTO library (library_id, name) VALUES (1, 'Test Library')")
            conn.execute(
                "INSERT INTO source_corpus (corpus_id, project_id, name) VALUES (1, 1, 'Test Corpus')"
            )
            conn.execute(
                "INSERT INTO source_document (doc_id, corpus_id, file_path, file_name, file_ext, sha256) "
                "VALUES (1, 1, '/test', 'test.txt', '.txt', 'abc123')"
            )
            conn.execute(
                "INSERT INTO document_sentence (sentence_id, doc_id, sent_index, text) "
                "VALUES (1, 1, 0, 'Test sentence')"
            )
            conn.commit()

            # Drop FTS tables
            conn.execute("DROP TABLE IF EXISTS sentence_fts")
            conn.commit()

            # Verify sentence_fts is gone and document_sentence has data
            sentence_fts_exists, _ = check_fts_exists(conn)
            assert not sentence_fts_exists

            cursor = conn.execute("SELECT COUNT(*) FROM document_sentence")
            assert cursor.fetchone()[0] == 1

            # Rebuild FTS
            results = ensure_fts_tables(conn, schema="main", rebuild=True)

            # Verify FTS was created and populated
            assert results["sentence_fts"] is True

            cursor = conn.execute("SELECT COUNT(*) FROM sentence_fts")
            fts_count = cursor.fetchone()[0]
            assert fts_count == 1, "sentence_fts should have 1 row after rebuild"

        finally:
            conn.close()
            db_manager.close()

    def test_triggers_work_after_ensure_fts(self, temp_db):
        """Test that triggers work correctly after ensure_fts_tables."""
        db_manager = DatabaseManager(temp_db)
        db_manager.apply_migrations()

        conn = sqlite3.connect(str(temp_db))
        try:
            # Insert base data
            conn.execute("INSERT INTO library (library_id, name) VALUES (1, 'Test Library')")
            conn.execute(
                "INSERT INTO dict_project (project_id, library_id, name) VALUES (1, 1, 'Test')"
            )
            conn.execute(
                "INSERT INTO source_corpus (corpus_id, project_id, name) VALUES (1, 1, 'Test')"
            )
            conn.execute(
                "INSERT INTO source_document (doc_id, corpus_id, file_path, file_name, file_ext, sha256) "
                "VALUES (1, 1, '/test', 'test.txt', '.txt', 'abc123')"
            )
            conn.commit()

            # Drop FTS and recreate
            conn.execute("DROP TABLE IF EXISTS sentence_fts")
            conn.commit()

            ensure_fts_tables(conn, schema="main", rebuild=False)

            # Insert a sentence (should trigger FTS insert)
            conn.execute(
                "INSERT INTO document_sentence (sentence_id, doc_id, sent_index, text) "
                "VALUES (1, 1, 0, 'Test sentence')"
            )
            conn.commit()

            # Verify FTS was updated by trigger
            cursor = conn.execute("SELECT COUNT(*) FROM sentence_fts WHERE sentence_id = 1")
            assert cursor.fetchone()[0] == 1, "Trigger should insert into sentence_fts"

            # Update sentence (should trigger FTS update)
            conn.execute(
                "UPDATE document_sentence SET text = 'Updated sentence' WHERE sentence_id = 1"
            )
            conn.commit()

            cursor = conn.execute("SELECT text FROM sentence_fts WHERE sentence_id = 1")
            result = cursor.fetchone()
            assert result is not None
            assert result[0] == "Updated sentence", "Trigger should update sentence_fts"

            # Delete sentence (should trigger FTS delete)
            conn.execute("DELETE FROM document_sentence WHERE sentence_id = 1")
            conn.commit()

            cursor = conn.execute("SELECT COUNT(*) FROM sentence_fts WHERE sentence_id = 1")
            assert cursor.fetchone()[0] == 0, "Trigger should delete from sentence_fts"

        finally:
            conn.close()
            db_manager.close()

    def test_no_error_on_delete_with_missing_fts(self, temp_db):
        """Test that delete doesn't crash when FTS is missing (before fix)."""
        db_manager = DatabaseManager(temp_db)
        db_manager.apply_migrations()

        conn = sqlite3.connect(str(temp_db))
        try:
            # Insert test data
            conn.execute("INSERT INTO library (library_id, name) VALUES (1, 'Test')")
            conn.execute(
                "INSERT INTO dict_project (project_id, library_id, name) VALUES (1, 1, 'Test')"
            )
            conn.execute(
                "INSERT INTO source_corpus (corpus_id, project_id, name) VALUES (1, 1, 'Test')"
            )
            conn.execute(
                "INSERT INTO source_document (doc_id, corpus_id, file_path, file_name, file_ext, sha256) "
                "VALUES (1, 1, '/test', 'test.txt', '.txt', 'abc123')"
            )
            conn.execute(
                "INSERT INTO document_sentence (sentence_id, doc_id, sent_index, text) "
                "VALUES (1, 1, 0, 'Test')"
            )
            conn.commit()

            # Drop FTS to simulate the bug
            conn.execute("DROP TABLE IF EXISTS sentence_fts")
            conn.commit()

            # Ensure FTS exists (the fix)
            ensure_fts_tables(conn, schema="main", rebuild=False)

            # Now delete should work without error
            conn.execute("DELETE FROM document_sentence WHERE sentence_id = 1")
            conn.commit()

            # Verify deletion succeeded
            cursor = conn.execute("SELECT COUNT(*) FROM document_sentence")
            assert cursor.fetchone()[0] == 0

        finally:
            conn.close()
            db_manager.close()


class TestProjectLifecycle:
    """Test full project lifecycle with FTS."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        yield db_path
        if db_path.exists():
            db_path.unlink()

    def test_project_create_delete_no_fts_error(self, temp_db):
        """Test that project creation and deletion works without FTS errors."""
        from app.services.db_service import DBService
        from app.services.project_service import ProjectService

        # Reset singleton
        DBService._instance = None
        DBService._db_manager = None

        # Initialize DB service (this also applies migrations)
        db_service = DBService.initialize(temp_db)
        project_service = ProjectService()

        try:
            with db_service.get_session() as session:
                # Create default library
                library = project_service.get_or_create_default_library(session)

                # Create project
                project = project_service.create_project(
                    session, name="Test Project", library=library
                )
                project_id = project.project_id
                session.commit()

            # Verify project exists
            with db_service.get_session() as session:
                project = project_service.get_project(session, project_id)
                assert project is not None
                assert project.name == "Test Project"

            # Delete project (this should NOT crash even if FTS was missing)
            with db_service.get_session() as session:
                report = project_service.delete_project(session, project_id)
                assert report.success is True, f"Delete failed: {report.error_message}"

            # Verify project is gone
            with db_service.get_session() as session:
                project = project_service.get_project(session, project_id)
                assert project is None

        finally:
            DBService.shutdown()
            DBService._instance = None
            DBService._db_manager = None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
