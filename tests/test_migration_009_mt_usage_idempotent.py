import sqlite3
from pathlib import Path

from app.infra.db import DatabaseManager
from app.infra.db_path_resolver import get_supported_schema_version


def _migration_version(path: Path) -> int:
    return int(path.name.split("_", 1)[0])


def _apply_migrations_through(db_path: Path, max_version: int) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        for sql_file in sorted(Path("app/infra/migrations").glob("*.sql")):
            if _migration_version(sql_file) > max_version:
                continue
            conn.executescript(sql_file.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


def test_migration_009_is_idempotent_when_table_preexists(tmp_path: Path) -> None:
    """Regression: startup must not fail when mt_usage exists but schema_version is 8."""
    db_path = tmp_path / "migration_009_skew.db"
    _apply_migrations_through(db_path, max_version=8)

    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS mt_usage (
                usage_id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider_id TEXT NOT NULL,
                period_type TEXT NOT NULL,
                period_key TEXT NOT NULL,
                char_count INTEGER NOT NULL DEFAULT 0,
                request_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(provider_id, period_type, period_key)
            );
            CREATE INDEX IF NOT EXISTS idx_mt_usage_lookup
                ON mt_usage(provider_id, period_type, period_key);
            """
        )
        conn.execute("UPDATE schema_meta SET value='8' WHERE key='schema_version'")
        conn.commit()
    finally:
        conn.close()

    db_manager = DatabaseManager(db_path)
    try:
        db_manager.apply_migrations()
    finally:
        db_manager.close()

    conn = sqlite3.connect(str(db_path))
    try:
        schema_version = int(
            conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0]
        )
        assert schema_version == get_supported_schema_version()

        assert (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='mt_usage'"
            ).fetchone()
            is not None
        )
        assert (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_mt_usage_lookup'"
            ).fetchone()
            is not None
        )
    finally:
        conn.close()
