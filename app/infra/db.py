"""Database connection and migration management."""
import logging
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, event, text
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

        # Enable SQLite safety PRAGMAs for every new connection.
        @event.listens_for(self.engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            # Keep write-lock windows survivable across workers and UI actions.
            cursor.execute("PRAGMA busy_timeout=15000")
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
            self._ensure_fts_health()  # Still check FTS even if no migrations dir
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
            # CRITICAL FIX (Task 12): Always check FTS health, even if no migrations pending
            self._ensure_fts_health()
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
                        try:
                            cursor.executescript(sql_content)
                            raw_conn.commit()
                            logger.info(f"Migration {sql_file.name} applied successfully")
                        except Exception as script_err:
                            # Guard: if columns were already added in a previous partial run
                            # (schema_version not updated), treat as already applied rather
                            # than crashing the app.
                            if "duplicate column name" in str(script_err).lower():
                                logger.warning(
                                    f"Migration {sql_file.name} already partially applied "
                                    f"({script_err}) — forcing schema_version to "
                                    f"{migration_version}"
                                )
                                try:
                                    raw_conn.rollback()
                                except Exception:
                                    pass
                                cursor2 = raw_conn.cursor()
                                cursor2.execute(
                                    "UPDATE schema_meta SET value = ? "
                                    "WHERE key = 'schema_version'",
                                    (str(migration_version),),
                                )
                                raw_conn.commit()
                            else:
                                try:
                                    raw_conn.rollback()
                                except Exception:
                                    pass
                                raise
                    finally:
                        raw_conn.close()

                # NEW: Cleanup old backups (retention policy)
                backup_dir = self.db_path.parent / "backups"
                backup_service.cleanup_old_backups(
                    backup_dir, max_count=10, max_age_days=30
                )

        except RuntimeError as e:
            # Lock acquisition or backup failure
            logger.error(f"Migration aborted: {e}")
            raise

        # CRITICAL FIX (Task 12): Always check FTS health after migrations
        self._ensure_fts_health()

        # Task 19: Auto-backfill tm_global if needed (after migration 015)
        self._backfill_tm_global_if_needed()

    def _ensure_fts_health(self) -> None:
        """Ensure FTS5 tables and triggers exist. Runs on EVERY startup.

        This is a critical self-healing mechanism for Task 12:
        - If FTS tables are missing (e.g., after corruption or manual deletion),
          they are recreated and populated from base tables.
        - Prevents "no such table: main.sentence_fts" errors during NLP processing.
        """
        from app.infra.fts_manager import ensure_fts_tables

        raw_conn = self.engine.raw_connection()
        try:
            # rebuild=True ensures that if tables are just created, they get populated
            ensure_fts_tables(raw_conn, schema="main", rebuild=True)
            logger.info("FTS health check passed")
        except Exception as e:
            logger.error(f"FTS health check failed: {e}")
            # Don't raise - allow app to start, FTS operations will fail gracefully
        finally:
            raw_conn.close()

    def _backfill_tm_global_if_needed(self) -> None:
        """Backfill tm_global from existing tm_entry data if table is empty.

        This is a one-time operation after migration 015:
        - If tm_global table exists AND has 0 rows AND tm_entry has >0 rows → run backfill
        - Safe to run multiple times (idempotent via UNIQUE constraint)
        """
        from sqlalchemy import text

        try:
            with self.engine.connect() as conn:
                # Check if tm_global table exists
                result = conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table' AND name='tm_global'")
                ).fetchone()
                if not result:
                    return  # Table doesn't exist yet, skip

                # Check if tm_global is empty
                tm_global_count = conn.execute(text("SELECT COUNT(*) FROM tm_global")).scalar()
                if tm_global_count > 0:
                    logger.debug("tm_global already populated, skipping backfill")
                    return  # Already populated

                # Check if tm_entry has data to backfill
                tm_entry_count = conn.execute(text("SELECT COUNT(*) FROM tm_entry")).scalar()
                if tm_entry_count == 0:
                    logger.debug("No tm_entry records to backfill")
                    return  # Nothing to backfill

            # Run backfill
            logger.info(f"Auto-backfilling tm_global from {tm_entry_count} tm_entry records...")
            from app.services.tm_global_service import TMGlobalService

            session = self.SessionLocal()
            try:
                service = TMGlobalService()
                stats = service.backfill(session, chunk_size=500, dry_run=False)
                logger.info(
                    f"tm_global backfill complete: {stats['groups_created']} rows created, "
                    f"{stats['entries_linked']} entries linked"
                )
            except Exception as e:
                logger.error(f"tm_global backfill failed: {e}")
                session.rollback()
            finally:
                session.close()

        except Exception as e:
            logger.error(f"tm_global backfill check failed: {e}")
            # Don't raise - allow app to start

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
