"""Tests for deterministic FTS schema repair."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.infra.fts_manager import ensure_fts_tables
from scripts import repair_fts_schema as repair_mod


def _create_minimal_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
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
            CREATE TABLE term_search (
                term_rowid INTEGER PRIMARY KEY,
                he_term TEXT,
                ru_translation TEXT,
                notes TEXT,
                project_id INTEGER,
                kind TEXT,
                lemma_id INTEGER,
                ngram_id INTEGER
            )
            """
        )
        conn.executemany(
            "INSERT INTO document_sentence(sentence_id, doc_id, text) VALUES (?, ?, ?)",
            [(1, 10, "hello world"), (2, 10, "second line")],
        )
        conn.execute(
            """
            INSERT INTO term_search(
                term_rowid, he_term, ru_translation, notes, project_id, kind, lemma_id, ngram_id
            )
            VALUES (1, 'shalom', 'privet', 'note', 1, 'lemma', 1, NULL)
            """
        )
        conn.commit()
        ensure_fts_tables(conn, schema="main", rebuild=True)
    finally:
        conn.close()


def _inject_sentence_fts_duplicates(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA writable_schema=ON")
        for name in ["sentence_fts"] + [f"sentence_fts{suffix}" for suffix in repair_mod.FTS_SHADOW_SUFFIXES]:
            conn.execute(
                """
                INSERT INTO sqlite_master(type, name, tbl_name, rootpage, sql)
                SELECT type, name, tbl_name, rootpage, sql
                FROM sqlite_master
                WHERE name = ?
                LIMIT 1
                """,
                (name,),
            )
        conn.execute("PRAGMA writable_schema=OFF")
        conn.commit()
    finally:
        conn.close()


def test_repair_fts_schema_repairs_duplicate_sentence_fts_entries(tmp_path: Path) -> None:
    db_path = tmp_path / "malformed_fts.db"
    _create_minimal_db(db_path)
    _inject_sentence_fts_duplicates(db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        try:
            conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
            assert False, "Expected malformed schema before repair"
        except sqlite3.DatabaseError as exc:
            assert "sentence_fts" in str(exc)
    finally:
        conn.close()

    summary = repair_mod.repair_fts_schema(
        db_path=db_path,
        dry_run=False,
        backup=False,
    )
    assert summary["status"] == "REPAIRED"
    assert summary["error"] is None

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()

        dup_count = conn.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT name
                FROM sqlite_master
                WHERE name IN (
                    'sentence_fts',
                    'sentence_fts_data',
                    'sentence_fts_idx',
                    'sentence_fts_content',
                    'sentence_fts_docsize',
                    'sentence_fts_config'
                )
                GROUP BY name
                HAVING COUNT(*) > 1
            )
            """
        ).fetchone()[0]
        assert dup_count == 0

        sentence_count = conn.execute("SELECT COUNT(*) FROM document_sentence").fetchone()[0]
        sentence_fts_count = conn.execute("SELECT COUNT(*) FROM sentence_fts").fetchone()[0]
        assert sentence_count == sentence_fts_count

        term_count = conn.execute("SELECT COUNT(*) FROM term_search").fetchone()[0]
        term_fts_count = conn.execute("SELECT COUNT(*) FROM term_fts").fetchone()[0]
        assert term_count == term_fts_count

        conn.execute("SELECT sentence_id FROM sentence_fts WHERE sentence_fts MATCH 'hello'").fetchall()
        conn.execute("SELECT term_rowid FROM term_fts WHERE term_fts MATCH 'shalom'").fetchall()
    finally:
        conn.close()


def test_repair_fts_schema_dry_run_reports_required_actions(tmp_path: Path) -> None:
    db_path = tmp_path / "malformed_fts_dry_run.db"
    _create_minimal_db(db_path)
    _inject_sentence_fts_duplicates(db_path)

    summary = repair_mod.repair_fts_schema(
        db_path=db_path,
        dry_run=True,
        backup=False,
    )
    assert summary["status"] == "FAILED"
    assert "dry-run" in str(summary.get("error", "")).lower()
    assert summary["issues_detected"]


def test_repair_fts_schema_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "idempotent_fts.db"
    _create_minimal_db(db_path)
    _inject_sentence_fts_duplicates(db_path)

    first = repair_mod.repair_fts_schema(
        db_path=db_path,
        dry_run=False,
        backup=False,
    )
    second = repair_mod.repair_fts_schema(
        db_path=db_path,
        dry_run=False,
        backup=False,
    )

    assert first["status"] == "REPAIRED"
    assert second["status"] == "OK"
    assert not second["issues_detected"]
