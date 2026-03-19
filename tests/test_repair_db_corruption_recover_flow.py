"""Tests for recover pipeline orchestration with mocked sqlite3 recover."""

from __future__ import annotations

import sqlite3
from pathlib import Path
import sys

from scripts import repair_db_corruption as mod


def _create_source_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE tm_entry (tm_id INTEGER PRIMARY KEY, project_id INTEGER, kind TEXT)"
        )
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
        conn.execute(
            "INSERT INTO tm_entry(tm_id, project_id, kind, src_norm) VALUES (1, 1, 'lemma', 'alpha')"
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


def _create_target_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE tm_entry (
                tm_id INTEGER PRIMARY KEY,
                project_id INTEGER,
                kind TEXT
            )
            """
        )
        conn.execute("INSERT INTO tm_entry(tm_id, project_id, kind) VALUES (1, 99, 'legacy')")
        conn.commit()
    finally:
        conn.close()


def test_repair_db_corruption_salvage_flow_success_with_mocked_recover(
    tmp_path: Path, monkeypatch
) -> None:
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


def test_restore_db_from_backup_moves_corrupt_target_aside_and_restores_backup(
    tmp_path: Path,
) -> None:
    target_db = tmp_path / "target.db"
    backup_db = tmp_path / "backup.db"
    _create_target_db(target_db)
    _create_recovered_db(backup_db)

    summary = mod.restore_db_from_backup(
        db_path=target_db,
        backup_db_path=backup_db,
        move_backup=False,
        apply_migrations=False,
    )

    assert summary["status"] == "RESTORED_OK"
    assert summary["corrupt_db_path"] is not None
    assert Path(summary["corrupt_db_path"]).exists()
    assert target_db.exists()
    assert backup_db.exists()
    assert summary["schema_version_before_migration"] == 1
    assert summary["schema_version_after_migration"] == 1
    assert summary["restored_diagnosis"]["status"] == "OK"

    conn = sqlite3.connect(str(target_db))
    try:
        row = conn.execute("SELECT tm_id, project_id, kind, src_norm FROM tm_entry").fetchone()
        assert row == (1, 1, "lemma", "alpha")
    finally:
        conn.close()


def test_restore_db_from_backup_runs_migrations_when_requested(tmp_path: Path, monkeypatch) -> None:
    target_db = tmp_path / "target.db"
    backup_db = tmp_path / "backup.db"
    _create_target_db(target_db)
    _create_recovered_db(backup_db)

    calls: list[Path] = []

    class _FakeDBService:
        @classmethod
        def shutdown(cls):
            return None

        @classmethod
        def initialize(cls, path):
            calls.append(Path(path))
            conn = sqlite3.connect(str(path))
            try:
                conn.execute("UPDATE schema_meta SET value='39' WHERE key='schema_version'")
                conn.commit()
            finally:
                conn.close()
            return cls()

    import app.services.db_service as db_service_mod

    monkeypatch.setattr(db_service_mod, "DBService", _FakeDBService)

    summary = mod.restore_db_from_backup(
        db_path=target_db,
        backup_db_path=backup_db,
        move_backup=False,
        apply_migrations=True,
    )

    assert summary["status"] == "RESTORED_OK"
    assert calls == [target_db]
    assert summary["schema_version_before_migration"] == 1
    assert summary["schema_version_after_migration"] == 39


def test_restore_db_from_backup_removes_source_backup_sidecars_when_moving(tmp_path: Path) -> None:
    target_db = tmp_path / "target.db"
    backup_db = tmp_path / "backup.db"
    _create_target_db(target_db)
    _create_recovered_db(backup_db)
    backup_shm = Path(f"{backup_db}-shm")
    backup_wal = Path(f"{backup_db}-wal")
    backup_shm.write_bytes(b"shm")
    backup_wal.write_bytes(b"")

    summary = mod.restore_db_from_backup(
        db_path=target_db,
        backup_db_path=backup_db,
        move_backup=True,
        apply_migrations=False,
    )

    assert summary["status"] == "RESTORED_OK"
    assert sorted(Path(path).name for path in summary["removed_backup_sidecars"]) == sorted(
        [backup_shm.name, backup_wal.name]
    )
    assert not backup_shm.exists()
    assert not backup_wal.exists()


def test_main_allows_restore_to_missing_target_path(tmp_path: Path, monkeypatch, capsys) -> None:
    target_db = tmp_path / "missing_target.db"
    backup_db = tmp_path / "backup.db"
    _create_recovered_db(backup_db)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "repair_db_corruption.py",
            "--db-path",
            str(target_db),
            "--restore-backup-path",
            str(backup_db),
            "--no-apply-migrations",
        ],
    )

    exit_code = mod.main()
    captured = capsys.readouterr()

    assert exit_code == 0
    assert target_db.exists()
    assert '"status": "RESTORED_OK"' in captured.out
