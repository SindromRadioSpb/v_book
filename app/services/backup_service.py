"""Migration backup service with retention policy.

This module provides automated backup creation before database migrations,
with configurable retention policies to prevent unlimited storage growth.
"""

import logging
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional

from app.services.db_snapshot_base import DBSnapshotBase

logger = logging.getLogger(__name__)


@dataclass
class BackupInfo:
    """Backup metadata."""

    backup_path: Path
    timestamp: str
    reason: str
    size_bytes: int
    sha256: str


class BackupService(DBSnapshotBase):
    """Migration backup service with retention policy."""

    def __init__(self, backup_dir: Optional[Path] = None):
        """
        Initialize backup service.

        Args:
            backup_dir: Directory for backups (default: <db_parent>/backups/)
        """
        self.backup_dir = backup_dir
        if backup_dir:
            self._ensure_directory(backup_dir)

    def create_migration_backup(
        self, db_path: Path, reason: str, backup_dir: Optional[Path] = None
    ) -> BackupInfo:
        """
        Create WAL-safe backup before migration.

        Args:
            db_path: Source database path
            reason: Human-readable reason (e.g., "pre_migration_004_to_005")
            backup_dir: Override backup directory (default: <db_parent>/backups/)

        Returns:
            BackupInfo with paths and metadata

        Raises:
            RuntimeError: If backup creation fails
            OSError: If disk space or permissions insufficient
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Determine backup directory
        if backup_dir is None:
            backup_dir = self.backup_dir or (db_path.parent / "backups")

        self._ensure_directory(backup_dir)

        # Check disk space (require 3x DB size minimum)
        db_size = db_path.stat().st_size
        required_space = db_size * 3

        try:
            import shutil
            stat = shutil.disk_usage(backup_dir)
            if stat.free < required_space:
                raise RuntimeError(
                    f"Insufficient disk space: {stat.free} bytes free, "
                    f"{required_space} bytes required"
                )
        except Exception as e:
            logger.warning(f"Could not check disk space: {e}")

        # Create backup filename
        backup_filename = f"backup_{timestamp}_{reason}.db"
        backup_path = backup_dir / backup_filename

        logger.info(f"Creating migration backup: {backup_path}")

        try:
            # Use shared base method (WAL-safe)
            self._create_snapshot_copy(db_path, backup_path)

            # Compute metadata
            sha256 = self._compute_sha256(backup_path)
            size_bytes = backup_path.stat().st_size

            logger.info(
                f"Backup created successfully: {backup_path} ({size_bytes} bytes, "
                f"SHA256: {sha256[:16]}...)"
            )

            return BackupInfo(
                backup_path=backup_path,
                timestamp=timestamp,
                reason=reason,
                size_bytes=size_bytes,
                sha256=sha256,
            )

        except Exception as e:
            # Clean up partial backup
            if backup_path.exists():
                try:
                    backup_path.unlink()
                except Exception:
                    pass

            logger.error(f"Backup creation failed: {e}")
            raise RuntimeError(f"Backup creation failed: {e}") from e

    def cleanup_old_backups(
        self,
        backup_dir: Path,
        max_count: int = 10,
        max_age_days: int = 30,
    ) -> int:
        """
        Remove old backups based on retention policy.

        Policy: Keep last max_count backups OR backups from last max_age_days
        (whichever is more permissive).

        Args:
            backup_dir: Directory containing backups
            max_count: Maximum number of backups to keep
            max_age_days: Maximum age of backups in days

        Returns:
            Number of backups deleted
        """
        if not backup_dir.exists():
            return 0

        backups = sorted(
            backup_dir.glob("backup_*.db"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,  # Newest first
        )

        if len(backups) <= max_count:
            logger.debug(f"No cleanup needed: {len(backups)} backups <= {max_count} max")
            return 0

        deleted_count = 0
        cutoff_date = datetime.now() - timedelta(days=max_age_days)

        # Keep newest max_count backups
        for old_backup in backups[max_count:]:
            backup_time = datetime.fromtimestamp(old_backup.stat().st_mtime)
            age_days = (datetime.now() - backup_time).days

            # Only delete if BOTH conditions met (older than age AND beyond count)
            if backup_time < cutoff_date:
                try:
                    old_backup.unlink()
                    logger.info(
                        f"Deleted old backup: {old_backup.name} (age: {age_days} days)"
                    )
                    deleted_count += 1
                except Exception as e:
                    logger.warning(f"Failed to delete backup {old_backup.name}: {e}")

        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} old backups")

        return deleted_count
