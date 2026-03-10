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
            CREATE INDEX idx_tm_entry_src_norm_partial
            ON tm_entry(src_norm)
            WHERE src_norm IS NOT NULL
            """
        )
        conn.execute(
            """
            CREATE TABLE document_sentence (
                sentence_id INTEGER PRIMARY KEY,
                doc_id INTEGER NOT NULL,
                text TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE sentence_nlp_snapshot (
                sentence_id INTEGER PRIMARY KEY,
                engine TEXT,
                engine_version TEXT,
                sentence_text_hash TEXT,
                payload_json TEXT,
                token_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            INSERT INTO tm_entry(tm_id, project_id, kind, src_norm, translation)
            VALUES (1, 1, 'lemma', 'alpha', 'beta')
            """
        )
        conn.execute(
            """
            INSERT INTO document_sentence(sentence_id, doc_id, text)
            VALUES (1, 10, 'alpha beta')
            """
        )
        conn.execute(
            """
            INSERT INTO sentence_nlp_snapshot(sentence_id, engine, engine_version, sentence_text_hash, payload_json, token_count)
            VALUES (1, 'mock', '1', 'hash', '[]', 0)
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
    assert diagnosis["sentence_snapshot_probe"]["ok"] is True
    assert diagnosis["failing_objects"] == []
    assert diagnosis["rootpage_matches"] == []


def test_diagnose_db_corruption_maps_sentence_snapshot_rootpage(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "rootpage.db"
    _create_healthy_db(db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        rootpage = int(
            conn.execute(
                "SELECT rootpage FROM sqlite_master WHERE name='sentence_nlp_snapshot'"
            ).fetchone()[0]
        )
    finally:
        conn.close()

    original_run_pragma = mod._run_pragma

    def _fake_run_pragma(conn, pragma_sql: str):
        if pragma_sql == "PRAGMA quick_check(10)":
            return {
                "ok": False,
                "rows": [f"*** in database main *** Tree {rootpage} page 1 cell 0: invalid page number"],
                "error": None,
                "sql": pragma_sql,
            }
        return original_run_pragma(conn, pragma_sql)

    monkeypatch.setattr(mod, "_run_pragma", _fake_run_pragma)

    diagnosis = mod.diagnose_db_corruption(db_path, deep=False)

    assert diagnosis["status"] == "CORRUPT"
    assert diagnosis["quick_check_rootpages"] == [rootpage]
    assert any(
        match["name"] == "sentence_nlp_snapshot" and int(match["rootpage"]) == rootpage
        for match in diagnosis["rootpage_matches"]
    )
