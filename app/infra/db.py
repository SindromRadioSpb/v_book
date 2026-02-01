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
        """Apply SQL migrations from the migrations folder."""
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

        # Apply migrations
        for sql_file in sql_files:
            migration_version = self._extract_version(sql_file.name)
            if migration_version <= current_version:
                logger.debug(f"Skipping migration {sql_file.name} (already applied)")
                continue

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
