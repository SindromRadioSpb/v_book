"""Database service - central access point for all DB operations."""
import logging
from pathlib import Path
from typing import Optional

from app.infra.db import DatabaseManager, ReadOnlyDatabaseManager

logger = logging.getLogger(__name__)


class DBService:
    """Singleton service for database access."""

    _instance: Optional["DBService"] = None
    _db_manager: Optional[DatabaseManager] = None

    # PERF-SCALE PATCH-A: reference DB registry.
    # Maps project_id (int) → ReadOnlyDatabaseManager for each attached reference DB.
    _ref_managers: dict[int, ReadOnlyDatabaseManager] = {}

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
        """Create a new database session (write pool)."""
        return self.db_manager.get_session()

    def get_read_session(self):
        """Create a new read-optimised session (PERF-SCALE PATCH-C).

        Use for workers that only SELECT: page loads, FTS/LIKE searches,
        concordance, TM search.  Never commit or mutate ORM objects.
        """
        return self.db_manager.get_read_session()

    def recover_from_crash(self) -> int:
        """
        Detect and recover from unclean shutdown.

        Finds all ProcessorRun with status='running' and:
        1. Update status to 'failed'
        2. Set stage/error_message to terminal recovery state
        3. Set finished_at to current time
        4. Create RunError with reason 'Recovered after unclean shutdown'

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
                run.stage = "failed"
                if not getattr(run, "error_message", None):
                    run.error_message = (
                        "Process terminated unexpectedly - recovered on restart"
                    )
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

    # ------------------------------------------------------------------
    # PERF-SCALE PATCH-A: reference DB helpers
    # ------------------------------------------------------------------

    @classmethod
    def attach_reference(cls, project_id: int, db_path: str | Path) -> None:
        """Open a read-only manager for a reference project and register it.

        Safe to call multiple times for the same project_id — if a manager is
        already registered and points to the same path it is left unchanged;
        if the path differs the old manager is closed first.

        Args:
            project_id: PK of the reference project in dict_project.
            db_path:    Absolute path to the external SQLite DB file.

        Raises:
            FileNotFoundError: if db_path does not exist.
        """
        db_path = Path(db_path)
        existing = cls._ref_managers.get(project_id)
        if existing is not None:
            if existing.db_path == db_path:
                logger.debug(
                    "Reference DB for project %d already attached at %s",
                    project_id,
                    db_path,
                )
                return
            # Path changed — close old manager before opening new one.
            existing.close()

        manager = ReadOnlyDatabaseManager(db_path)
        cls._ref_managers[project_id] = manager
        logger.info(
            "Attached reference DB for project %d → %s", project_id, db_path
        )

    @classmethod
    def get_ref_session(cls, project_id: int):
        """Return a new read-only session for the given reference project.

        Args:
            project_id: PK of the reference project.

        Returns:
            A SQLAlchemy Session bound to the reference DB engine.

        Raises:
            KeyError: if the reference DB is not attached. Call attach_reference() first.
        """
        manager = cls._ref_managers.get(project_id)
        if manager is None:
            raise KeyError(
                f"No reference DB attached for project {project_id}. "
                "Call DBService.attach_reference() first."
            )
        return manager.get_session()

    @classmethod
    def detach_reference(cls, project_id: int) -> None:
        """Close and unregister the reference DB for a project.

        No-op if the project has no attached reference DB.

        Args:
            project_id: PK of the reference project.
        """
        manager = cls._ref_managers.pop(project_id, None)
        if manager is not None:
            manager.close()
            logger.info("Detached reference DB for project %d", project_id)

    @classmethod
    def shutdown(cls) -> None:
        """Shutdown the database service."""
        # Close all reference DBs first.
        for pid, mgr in list(cls._ref_managers.items()):
            try:
                mgr.close()
            except Exception as e:
                logger.warning("Error closing reference DB for project %d: %s", pid, e)
        cls._ref_managers.clear()

        if cls._db_manager:
            cls._db_manager.close()
            cls._db_manager = None
            cls._instance = None
            logger.info("DBService shutdown")
