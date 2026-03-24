"""Tests for DatabaseManager._run_migration_skipping_duplicate_columns.

Verifies that when a migration fails with 'duplicate column name',
the runner correctly re-executes only non-DDL statements (backfill UPDATEs,
index creation) while skipping ALTER TABLE ADD COLUMN statements.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from app.infra.db import DatabaseManager


@pytest.fixture()
def raw_db(tmp_path: Path):
    """Fresh SQLite DB with schema_meta and a test table."""
    db_path = tmp_path / "test_recovery.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT);
        INSERT INTO schema_meta VALUES ('schema_version', '47');

        CREATE TABLE item (id INTEGER PRIMARY KEY, status TEXT, source TEXT);
        INSERT INTO item (status) VALUES ('active');
        INSERT INTO item (status) VALUES ('active');
        INSERT INTO item (status) VALUES (NULL);
        """
    )
    conn.commit()
    yield conn, db_path
    conn.close()


def _make_manager(db_path: Path) -> DatabaseManager:
    mgr = DatabaseManager(db_path)
    return mgr


def test_skips_alter_table_executes_update(raw_db):
    """Non-DDL UPDATE runs; ALTER TABLE ADD COLUMN is skipped."""
    conn, db_path = raw_db
    mgr = _make_manager(db_path)

    sql = """
BEGIN;
ALTER TABLE item ADD COLUMN source TEXT;
UPDATE item SET source = 'auto' WHERE status IS NOT NULL AND source IS NULL;
UPDATE schema_meta SET value = '48' WHERE key = 'schema_version';
COMMIT;
"""
    mgr._run_migration_skipping_duplicate_columns(conn, sql, 48, "048_test.sql")

    rows = conn.execute("SELECT source FROM item").fetchall()
    # Two rows had status NOT NULL → source should be 'auto'
    assert rows.count(("auto",)) == 2
    # One row had status NULL → source stays NULL
    assert rows.count((None,)) == 1

    version = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0]
    assert version == "48"

    mgr.close()


def test_transaction_boundaries_skipped(raw_db):
    """BEGIN / COMMIT tokens are ignored without error."""
    conn, db_path = raw_db
    mgr = _make_manager(db_path)

    sql = "BEGIN;\nUPDATE schema_meta SET value='48' WHERE key='schema_version';\nCOMMIT;\n"
    # Should not raise even though BEGIN/COMMIT appear as standalone statements
    mgr._run_migration_skipping_duplicate_columns(conn, sql, 48, "048_test.sql")

    version = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0]
    assert version == "48"

    mgr.close()


def test_schema_version_always_updated_even_if_statement_fails(raw_db):
    """schema_version is bumped even when a non-DDL statement produces a warning."""
    conn, db_path = raw_db
    mgr = _make_manager(db_path)

    # UPDATE referencing a non-existent column — should be skipped with a warning,
    # but schema_version must still be set.
    sql = """
BEGIN;
ALTER TABLE item ADD COLUMN source TEXT;
UPDATE item SET nonexistent_col = 'x' WHERE id = 1;
UPDATE schema_meta SET value = '48' WHERE key = 'schema_version';
COMMIT;
"""
    mgr._run_migration_skipping_duplicate_columns(conn, sql, 48, "048_test.sql")

    version = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0]
    assert version == "48"

    mgr.close()


def test_idempotent_backfill_is_noop_when_already_filled(raw_db):
    """Running the backfill a second time is a no-op (WHERE source IS NULL matches 0 rows)."""
    conn, db_path = raw_db
    # Pre-fill source so backfill has nothing to do (column already exists in fixture schema)
    conn.execute("UPDATE item SET source = 'auto'")
    conn.commit()

    mgr = _make_manager(db_path)
    sql = """
BEGIN;
ALTER TABLE item ADD COLUMN source TEXT;
UPDATE item SET source = 'auto' WHERE status IS NOT NULL AND source IS NULL;
UPDATE schema_meta SET value = '48' WHERE key = 'schema_version';
COMMIT;
"""
    mgr._run_migration_skipping_duplicate_columns(conn, sql, 48, "048_test.sql")

    # All rows should still be 'auto'
    rows = conn.execute("SELECT source FROM item").fetchall()
    assert all(r == ("auto",) for r in rows)

    mgr.close()
