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

    def recover_from_crash(self) -> int:
        """
        Detect and recover from unclean shutdown.

        Finds all ProcessorRun with status='running' and:
        1. Update status to 'failed'
        2. Set finished_at to current time
        3. Create RunError with reason 'Recovered after unclean shutdown'

        Returns:
            Number of runs recovered
        """
        from app.infra.sa_models import ProcessorRun, RunError
        from datetime import datetime, timezone

        with self.get_session() as session:
            # Find all running jobs (explicit ORDER BY for determinism)
            running_runs = (
                session.query(ProcessorRun)
                .filter(ProcessorRun.status == "running")
                .order_by(ProcessorRun.run_id)
                .all()
            )

            if not running_runs:
                logger.debug("No crash recovery needed")
                return 0

            logger.warning(
                f"Found {len(running_runs)} unfinished runs - recovering..."
            )

            for run in running_runs:
                run.status = "failed"
                run.finished_at = datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%S.%fZ"
                )

                # Create error record
                error = RunError(
                    run_id=run.run_id,
                    doc_id=None,
                    stage="crash_recovery",
                    message="Process terminated unexpectedly - recovered on restart",
                )
                session.add(error)

            session.commit()
            logger.info(f"Recovered {len(running_runs)} runs")

            return len(running_runs)

    @classmethod
    def shutdown(cls) -> None:
        """Shutdown the database service."""
        if cls._db_manager:
            cls._db_manager.close()
            cls._db_manager = None
            cls._instance = None
            logger.info("DBService shutdown")
