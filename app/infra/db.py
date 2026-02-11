"""Database connection and migration management."""
import logging
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages database connections and migrations."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        db_url = f"sqlite:///{self.db_path}"
        self.engine = create_engine(
            db_url,
            echo=False,
            connect_args={"check_same_thread": False},
        )

        # Enable WAL mode and foreign keys
        @event.listens_for(Engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

        self.SessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=self.engine
        )

        logger.info(f"Database initialized at {self.db_path}")

    def get_session(self) -> Session:
        """Create a new database session."""
        return self.SessionLocal()

    def apply_migrations(self) -> None:
        """Apply SQL migrations from the migrations folder with automatic backup."""
        migrations_dir = Path(__file__).parent / "migrations"
        if not migrations_dir.exists():
            logger.warning(f"Migrations directory not found: {migrations_dir}")
            return

        sql_files = sorted(migrations_dir.glob("*.sql"))

        # Check current schema version
        current_version = 0
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT value FROM schema_meta WHERE key='schema_version'")
                ).fetchone()
                current_version = int(result[0]) if result else 0
        except Exception:
            current_version = 0

        logger.info(f"Current schema version: {current_version}")

        # Determine pending migrations
        pending_migrations = [
            sql_file
            for sql_file in sql_files
            if self._extract_version(sql_file.name) > current_version
        ]

        if not pending_migrations:
            logger.debug("No pending migrations")
            return

        # NEW: Acquire migration lock to prevent concurrent migrations
        from app.infra.process_lock import ProcessLock

        lock_path = self.db_path.parent / "migrate.lock"

        try:
            with ProcessLock(lock_path, timeout_seconds=30):
                # NEW: Create backup BEFORE applying migrations
                from app.services.backup_service import BackupService

                backup_service = BackupService()

                target_version = self._extract_version(pending_migrations[-1].name)
                reason = f"pre_migration_{current_version}_to_{target_version}"

                try:
                    backup_info = backup_service.create_migration_backup(
                        self.db_path, reason
                    )
                    logger.info(f"Migration backup created: {backup_info.backup_path}")
                except Exception as e:
                    logger.error(f"Backup failed: {e}")
                    raise RuntimeError(
                        f"Cannot proceed with migration - backup failed: {e}"
                    ) from e

                # Apply migrations
                for sql_file in pending_migrations:
                    migration_version = self._extract_version(sql_file.name)
                    logger.info(f"Applying migration: {sql_file.name}")
                    sql_content = sql_file.read_text(encoding="utf-8")

                    # Execute migration using raw DBAPI connection (supports triggers)
                    raw_conn = self.engine.raw_connection()
                    try:
                        cursor = raw_conn.cursor()
                        cursor.executescript(sql_content)
                        raw_conn.commit()
                        logger.info(f"Migration {sql_file.name} applied successfully")
                    finally:
                        raw_conn.close()

                # NEW: Cleanup old backups (retention policy)
                backup_dir = self.db_path.parent / "backups"
                backup_service.cleanup_old_backups(
                    backup_dir, max_count=10, max_age_days=30
                )

                # CRITICAL: Ensure FTS tables exist after migrations
                # This handles cases where FTS tables were deleted or migrations failed
                from app.infra.fts_manager import ensure_fts_tables
                raw_conn = self.engine.raw_connection()
                try:
                    ensure_fts_tables(raw_conn, schema="main", rebuild=False)
                    logger.info("Verified FTS tables exist after migrations")
                finally:
                    raw_conn.close()

        except RuntimeError as e:
            # Lock acquisition or backup failure
            logger.error(f"Migration aborted: {e}")
            raise

    @staticmethod
    def _extract_version(filename: str) -> int:
        """Extract version number from migration filename (e.g., '001_init.sql' -> 1)."""
        try:
            return int(filename.split("_")[0])
        except (ValueError, IndexError):
            return 0

    def close(self) -> None:
        """Close database connections."""
        self.engine.dispose()
        logger.info("Database connections closed")
