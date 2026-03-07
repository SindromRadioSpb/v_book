"""Tests for PERF-SCALE PATCH-A: reference project read-only mode.

Covers:
- ReferenceProjectReadOnlyError raises correctly
- assert_not_reference_project passes for normal project, raises for reference
- ReadOnlyDatabaseManager opens DB and enforces PRAGMA query_only
- ReadOnlyDatabaseManager raises FileNotFoundError for missing DB
- DBService.attach_reference / get_ref_session / detach_reference lifecycle
- DBService.shutdown closes all reference managers
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.infra.reference_guard import (
    ReferenceProjectReadOnlyError,
    assert_not_reference_project,
)
from app.infra.db import ReadOnlyDatabaseManager
from app.services.db_service import DBService


# ---------------------------------------------------------------------------
# reference_guard tests
# ---------------------------------------------------------------------------


def test_guard_passes_for_normal_project():
    """assert_not_reference_project does NOT raise for is_reference=0."""
    assert_not_reference_project(project_id=42, is_reference=0, operation="delete")


def test_guard_raises_for_reference_project():
    """assert_not_reference_project raises for is_reference=1."""
    with pytest.raises(ReferenceProjectReadOnlyError) as exc_info:
        assert_not_reference_project(project_id=1, is_reference=1, operation="import")
    err = exc_info.value
    assert err.project_id == 1
    assert err.operation == "import"
    assert "read-only reference project" in str(err)


def test_guard_error_message_contains_operation():
    with pytest.raises(ReferenceProjectReadOnlyError, match="delete_corpus"):
        assert_not_reference_project(1, 1, "delete_corpus")


# ---------------------------------------------------------------------------
# ReadOnlyDatabaseManager tests
# ---------------------------------------------------------------------------


def _make_small_db() -> str:
    """Create a tiny SQLite DB with one table + one row; return its path."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE ref_data (id INTEGER PRIMARY KEY, val TEXT)")
    conn.execute("INSERT INTO ref_data VALUES (1, 'hello')")
    conn.commit()
    conn.close()
    return db_path


def test_ro_manager_missing_file_raises():
    with pytest.raises(FileNotFoundError, match="Reference DB not found"):
        ReadOnlyDatabaseManager("/nonexistent/path/db.db")


def test_ro_manager_opens_and_reads():
    db_path = _make_small_db()
    try:
        mgr = ReadOnlyDatabaseManager(db_path)
        with mgr.get_session() as session:
            result = session.execute(text("SELECT val FROM ref_data WHERE id=1")).scalar()
        assert result == "hello"
        mgr.close()
    finally:
        Path(db_path).unlink(missing_ok=True)


def test_ro_manager_query_only_pragma():
    """PRAGMA query_only should be ON; any write should fail."""
    db_path = _make_small_db()
    try:
        mgr = ReadOnlyDatabaseManager(db_path)
        with mgr.get_session() as session:
            with pytest.raises(OperationalError):
                session.execute(
                    text("INSERT INTO ref_data VALUES (99, 'forbidden')")
                )
                session.commit()
        mgr.close()
    finally:
        Path(db_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# DBService reference lifecycle
# ---------------------------------------------------------------------------


def test_dbservice_attach_and_get_ref_session():
    db_path = _make_small_db()
    try:
        DBService.attach_reference(project_id=999, db_path=db_path)
        with DBService.get_ref_session(999) as session:
            val = session.execute(
                text("SELECT val FROM ref_data WHERE id=1")
            ).scalar()
        assert val == "hello"
    finally:
        DBService.detach_reference(999)
        Path(db_path).unlink(missing_ok=True)


def test_dbservice_get_ref_session_not_attached_raises():
    with pytest.raises(KeyError, match="No reference DB attached for project 12345"):
        DBService.get_ref_session(12345)


def test_dbservice_detach_reference_noop_when_not_attached():
    """detach_reference must not raise if project has no manager."""
    DBService.detach_reference(99999)  # should not raise


def test_dbservice_attach_idempotent_same_path():
    """attach_reference called twice with same path must not raise."""
    db_path = _make_small_db()
    try:
        DBService.attach_reference(project_id=888, db_path=db_path)
        DBService.attach_reference(project_id=888, db_path=db_path)  # no-op
        with DBService.get_ref_session(888) as session:
            val = session.execute(
                text("SELECT val FROM ref_data WHERE id=1")
            ).scalar()
        assert val == "hello"
    finally:
        DBService.detach_reference(888)
        Path(db_path).unlink(missing_ok=True)


def test_dbservice_shutdown_closes_all_refs():
    """shutdown() must close all reference managers without error."""
    db1 = _make_small_db()
    db2 = _make_small_db()
    try:
        DBService.attach_reference(project_id=701, db_path=db1)
        DBService.attach_reference(project_id=702, db_path=db2)
        # Shutdown clears both without raising.
        DBService.shutdown()
        assert 701 not in DBService._ref_managers
        assert 702 not in DBService._ref_managers
    finally:
        # Restore singleton state (tests may share process).
        DBService._instance = None
        DBService._db_manager = None
        DBService._ref_managers.clear()
        Path(db1).unlink(missing_ok=True)
        Path(db2).unlink(missing_ok=True)
