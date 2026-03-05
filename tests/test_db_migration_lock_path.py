"""Tests for migration lock path override behavior."""

from pathlib import Path

from app.infra.db import DatabaseManager
from app.infra.process_lock import ProcessLock


def test_resolve_migration_lock_path_uses_env_override(tmp_path, monkeypatch):
    db_path = tmp_path / "data" / "sample.db"
    manager = DatabaseManager(db_path)
    override_dir = tmp_path / "locks"
    monkeypatch.setenv("HDLE_MIGRATION_LOCK_DIR", str(override_dir))

    lock_path = manager._resolve_migration_lock_path()

    assert lock_path == override_dir / "migrate.lock"
    assert lock_path.parent.exists()
    manager.close()


def test_resolve_migration_lock_path_defaults_to_db_parent(tmp_path, monkeypatch):
    db_path = tmp_path / "data" / "sample.db"
    manager = DatabaseManager(db_path)
    monkeypatch.delenv("HDLE_MIGRATION_LOCK_DIR", raising=False)

    lock_path = manager._resolve_migration_lock_path()

    assert lock_path == db_path.parent / "migrate.lock"
    manager.close()


def test_process_lock_file_lives_in_override_dir(tmp_path, monkeypatch):
    db_path = tmp_path / "data" / "sample.db"
    manager = DatabaseManager(db_path)
    override_dir = tmp_path / "isolated_locks"
    monkeypatch.setenv("HDLE_MIGRATION_LOCK_DIR", str(override_dir))

    lock_path = manager._resolve_migration_lock_path()
    with ProcessLock(lock_path, timeout_seconds=1):
        assert lock_path.exists()
        assert lock_path.parent == override_dir

    assert not lock_path.exists()
    manager.close()
