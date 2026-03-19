"""Tests for corruption detection."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts import repair_db_corruption as mod


def _create_db_then_truncate(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE tm_entry (tm_id INTEGER PRIMARY KEY, project_id INTEGER, kind TEXT)"
        )
        conn.execute("INSERT INTO tm_entry(tm_id, project_id, kind) VALUES (1, 1, 'lemma')")
        conn.commit()
    finally:
        conn.close()

    with db_path.open("r+b") as fh:
        fh.truncate(1024)


def test_diagnose_db_corruption_detects_truncated_db(tmp_path: Path) -> None:
    db_path = tmp_path / "corrupt.db"
    _create_db_then_truncate(db_path)

    diagnosis = mod.diagnose_db_corruption(db_path, deep=False)

    assert diagnosis["status"] == "CORRUPT"
    assert diagnosis["failing_objects"]
    assert diagnosis["quick_check"]["ok"] is False or diagnosis["tm_entry_probe"]["ok"] is False
