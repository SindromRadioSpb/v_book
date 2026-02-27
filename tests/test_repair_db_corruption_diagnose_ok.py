"""Tests for corruption diagnosis on healthy DB."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts import repair_db_corruption as mod


def _create_healthy_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE tm_entry (
                tm_id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                src_norm TEXT,
                translation TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX idx_tm_entry_project_kind
            ON tm_entry(project_id, kind)
            """
        )
        conn.execute(
            """
            INSERT INTO tm_entry(tm_id, project_id, kind, src_norm, translation)
            VALUES (1, 1, 'lemma', 'alpha', 'beta')
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_diagnose_db_corruption_returns_ok_for_healthy_db(tmp_path: Path) -> None:
    db_path = tmp_path / "healthy.db"
    _create_healthy_db(db_path)

    diagnosis = mod.diagnose_db_corruption(db_path, deep=False)

    assert diagnosis["status"] == "OK"
    assert diagnosis["quick_check"]["ok"] is True
    assert diagnosis["tm_entry_probe"]["ok"] is True
    assert diagnosis["failing_objects"] == []
