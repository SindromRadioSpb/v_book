"""Database service - central access point for all DB operations."""
import logging
from pathlib import Path
from typing import Optional

from app.infra.db import DatabaseManager

logger = logging.getLogger(__name__)


class DBService:
    """Singleton service for database access."""

    _instance: Optional["DBService"] = None
    _db_manager: Optional[DatabaseManager] = None

    @classmethod
    def initialize(cls, db_path: Path) -> "DBService":
        """Initialize the database service."""
        if cls._instance is None:
            cls._instance = cls()
            cls._db_manager = DatabaseManager(db_path)
            cls._db_manager.apply_migrations()
            logger.info("DBService initialized")
        return cls._instance

    @classmethod
    def get_instance(cls) -> "DBService":
        """Get the singleton instance."""
        if cls._instance is None:
            raise RuntimeError("DBService not initialized. Call initialize() first.")
        return cls._instance

    @property
    def db_manager(self) -> DatabaseManager:
        """Get the database manager."""
        if self._db_manager is None:
            raise RuntimeError("DBService not initialized")
        return self._db_manager

    def get_session(self):
        """Create a new database session."""
        return self.db_manager.get_session()

    @classmethod
    def shutdown(cls) -> None:
        """Shutdown the database service."""
        if cls._db_manager:
            cls._db_manager.close()
            cls._db_manager = None
            cls._instance = None
            logger.info("DBService shutdown")
