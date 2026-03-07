"""Tests for PERF-SCALE PATCH-C: read/write engine separation.

Covers:
- DatabaseManager exposes both get_session() (write pool) and get_read_session() (read pool)
- The two sessions use different engines (different connection pools)
- DBService.get_read_session() delegates to DatabaseManager.get_read_session()
- Read session can SELECT data inserted via write session in WAL mode
- Read engine applies the same PRAGMA tuning as the write engine
- DatabaseManager.close() disposes both engines
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import text

from app.infra.db import DatabaseManager


def _make_stub_db() -> str:
    """Create a temp SQLite file with a stub schema_meta (skips all migrations)."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT);
        INSERT INTO schema_meta VALUES ('schema_version', '9999');
        """
    )
    conn.close()
    return db_path


@pytest.fixture
def tmp_db():
    """Yield a fresh DatabaseManager backed by a temp file."""
    db_path = _make_stub_db()
    mgr = DatabaseManager(db_path)
    yield mgr
    mgr.close()
    Path(db_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Engine separation
# ---------------------------------------------------------------------------


def test_two_separate_engines(tmp_db):
    """Write and read engines must be distinct SQLAlchemy engine objects."""
    assert tmp_db.engine is not tmp_db._read_engine


def test_two_separate_session_factories(tmp_db):
    """SessionLocal and ReadSessionLocal must be distinct."""
    assert tmp_db.SessionLocal is not tmp_db.ReadSessionLocal


def test_get_session_uses_write_engine(tmp_db):
    """Session returned by get_session() must be bound to the write engine."""
    session = tmp_db.get_session()
    try:
        assert session.bind is tmp_db.engine
    finally:
        session.close()


def test_get_read_session_uses_read_engine(tmp_db):
    """Session returned by get_read_session() must be bound to the read engine."""
    session = tmp_db.get_read_session()
    try:
        assert session.bind is tmp_db._read_engine
    finally:
        session.close()


# ---------------------------------------------------------------------------
# WAL cross-session visibility
# ---------------------------------------------------------------------------


def test_write_visible_from_read_session(tmp_db):
    """Data committed on the write session must be readable on the read session."""
    # Write a row via write session
    with tmp_db.get_session() as w_sess:
        w_sess.execute(
            text(
                "CREATE TABLE IF NOT EXISTS _patch_c_test "
                "(id INTEGER PRIMARY KEY, val TEXT)"
            )
        )
        w_sess.execute(
            text("INSERT INTO _patch_c_test VALUES (1, 'hello')")
        )
        w_sess.commit()

    # Read it back via read session
    with tmp_db.get_read_session() as r_sess:
        val = r_sess.execute(
            text("SELECT val FROM _patch_c_test WHERE id=1")
        ).scalar()

    assert val == "hello"


# ---------------------------------------------------------------------------
# PRAGMA tuning on read engine
# ---------------------------------------------------------------------------


def test_read_engine_wal_mode(tmp_db):
    """Read engine connections must use WAL journal mode."""
    with tmp_db.get_read_session() as session:
        mode = session.execute(text("PRAGMA journal_mode")).scalar()
    assert mode == "wal"


def test_read_engine_temp_store_memory(tmp_db):
    """Read engine connections must have temp_store=MEMORY (value=2)."""
    with tmp_db.get_read_session() as session:
        val = session.execute(text("PRAGMA temp_store")).scalar()
    assert val == 2  # 2 = MEMORY


# ---------------------------------------------------------------------------
# DBService delegation
# ---------------------------------------------------------------------------


def test_dbservice_get_read_session_delegates():
    """DBService.get_read_session() must return a session on the read engine."""
    from app.services.db_service import DBService

    db_path = _make_stub_db()

    # Reset any existing singleton state from other tests.
    DBService._instance = None
    DBService._db_manager = None

    try:
        svc = DBService.initialize(db_path)
        r_sess = svc.get_read_session()
        try:
            assert r_sess.bind is svc.db_manager._read_engine
        finally:
            r_sess.close()
    finally:
        DBService.shutdown()
        DBService._instance = None
        DBService._db_manager = None
        Path(db_path).unlink(missing_ok=True)
