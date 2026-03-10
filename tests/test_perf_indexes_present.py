"""Regression checks for performance index migration."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from app.infra.db_path_resolver import get_supported_schema_version


def _apply_all_migrations(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        migrations = sorted(Path("app/infra/migrations").glob("*.sql"))
        for sql_file in migrations:
            sql = sql_file.read_text(encoding="utf-8")
            conn.executescript(sql)
        conn.commit()
    finally:
        conn.close()


def test_perf_indexes_present_after_migrations():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    try:
        _apply_all_migrations(db_path)

        conn = sqlite3.connect(str(db_path))
        try:
            idx_rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
            index_names = {row[0] for row in idx_rows}

            assert "idx_lemma_proj_doc_freq" in index_names
            assert "idx_doc_corpus_file_name" in index_names
            # Migration 030: sort covering indexes
            assert "idx_tm_entry_proj_updated_at" in index_names
            assert "idx_doc_corpus_imported_at" in index_names
            assert "idx_doc_corpus_sentence_count_sum" in index_names
            # Migration 031: fast corpus-level sentence pagination
            assert "idx_sentence_corpus_sent_id" in index_names
            # Migration 039: lemma delete cascade hardening for reprocess
            assert "idx_lemma_doc_lemma" in index_names
            assert "idx_lemma_proj_lemma" in index_names
            assert "idx_term_card_lemma" in index_names
            assert "idx_translation_memory_lemma_only" in index_names
            assert "idx_ngram_component_lemma" in index_names

            schema_version = conn.execute(
                "SELECT value FROM schema_meta WHERE key='schema_version'"
            ).fetchone()
            assert schema_version is not None
            assert int(schema_version[0]) == get_supported_schema_version()
        finally:
            conn.close()
    finally:
        db_path.unlink(missing_ok=True)
