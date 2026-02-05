"""Base class for DB snapshot/backup operations.

This module provides shared functionality for creating WAL-safe database copies,
computing file hashes, and managing storage directories.
"""

import sqlite3
import hashlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class DBSnapshotBase:
    """Base class for DB snapshot/backup operations (shared code)."""

    def _create_snapshot_copy(self, src_db: Path, dst_db: Path) -> None:
        """
        WAL-safe copy using sqlite3.backup() API.

        This method handles WAL files automatically - no need to copy
        *.db-wal and *.db-shm separately. The backup() API properly
        handles WAL mode databases by copying all committed data.

        Args:
            src_db: Source database path
            dst_db: Destination database path

        Raises:
            sqlite3.Error: If backup fails
            OSError: If file operations fail
        """
        logger.debug(f"Creating WAL-safe snapshot: {src_db} -> {dst_db}")

        src_conn = None
        dst_conn = None

        try:
            src_conn = sqlite3.connect(str(src_db))
            dst_conn = sqlite3.connect(str(dst_db))

            # Use sqlite3 backup API (WAL-aware, atomic)
            with dst_conn:
                src_conn.backup(dst_conn)

            logger.debug(f"Snapshot copy completed: {dst_db}")

        finally:
            if src_conn:
                src_conn.close()
            if dst_conn:
                dst_conn.close()

    def _compute_sha256(self, file_path: Path) -> str:
        """
        Compute SHA256 hash of file.

        Args:
            file_path: Path to file

        Returns:
            Hexadecimal SHA256 hash string

        Raises:
            OSError: If file cannot be read
        """
        sha256_hash = hashlib.sha256()

        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256_hash.update(chunk)

        return sha256_hash.hexdigest()

    def _ensure_directory(self, path: Path) -> None:
        """
        Create directory if not exists.

        Args:
            path: Directory path to create

        Raises:
            OSError: If directory cannot be created
        """
        path.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Ensured directory exists: {path}")
