"""Tests for recover pipeline orchestration with mocked sqlite3 recover."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts import repair_db_corruption as mod


def _create_source_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE tm_entry (tm_id INTEGER PRIMARY KEY, project_id INTEGER, kind TEXT)")
        conn.execute("INSERT INTO tm_entry(tm_id, project_id, kind) VALUES (1, 1, 'lemma')")
        conn.commit()
    finally:
        conn.close()


def _create_recovered_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE tm_entry (
                tm_id INTEGER PRIMARY KEY,
                project_id INTEGER,
                kind TEXT,
                src_norm TEXT
            )
            """
        )
        conn.execute("INSERT INTO tm_entry(tm_id, project_id, kind, src_norm) VALUES (1, 1, 'lemma', 'alpha')")

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
        conn.execute(
            """
            CREATE TABLE schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        conn.execute("INSERT INTO schema_meta(key, value) VALUES ('schema_version', '1')")
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


def test_repair_db_corruption_salvage_flow_success_with_mocked_recover(tmp_path: Path, monkeypatch) -> None:
    source_db = tmp_path / "source.db"
    recovered_db = tmp_path / "recovered.db"
    _create_source_db(source_db)

    monkeypatch.setattr(
        mod,
        "diagnose_db_corruption",
        lambda _db_path, deep=False: {
            "status": "CORRUPT",
            "quick_check": {"ok": False, "rows": ["database disk image is malformed"]},
            "tm_entry_probe": {"ok": False, "error": "database disk image is malformed"},
            "failing_objects": ["tm_entry"],
            "failing_sql_examples": [],
            "elapsed_s": 0.01,
        },
    )
    monkeypatch.setattr(mod, "_locate_sqlite3_binary", lambda _path: Path("sqlite3.exe"))

    def _fake_recover(**kwargs):
        _create_recovered_db(kwargs["recovered_db"])
        return {
            "ok": True,
            "recover_rc": 0,
            "apply_rc": 0,
            "recovered_exists": True,
            "recovered_size": kwargs["recovered_db"].stat().st_size,
            "log_path": str(kwargs["log_path"]),
            "error": None,
        }

    monkeypatch.setattr(mod, "_run_sqlite_recover_pipeline", _fake_recover)

    summary = mod.repair_db_corruption(
        db_path=source_db,
        deep=False,
        diagnose_only=False,
        backup=False,
        sqlite3_bin=None,
        recovered_db_path=recovered_db,
        fts_rebuild=False,
    )

    assert summary["status"] in {"SALVAGED_OK", "SALVAGED_WITH_WARNINGS"}
    assert summary["recovered_db_path"] == str(recovered_db)
    assert Path(summary["recovered_db_path"]).exists()
    assert summary["validation_results"]["quick_check"]["ok"] is True
    assert summary["validation_results"]["tm_entry_probe"]["ok"] is True
    assert summary["validation_results"]["sentence_snapshot_probe"]["ok"] is True
