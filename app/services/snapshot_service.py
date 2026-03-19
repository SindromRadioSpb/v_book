"""Snapshot service for creating and managing DB snapshots.

This module provides functionality for creating WAL-safe database snapshots,
typically used for testing, verification, and golden test scenarios.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.infra.resource_paths import ResourcePaths
from app.services.db_snapshot_base import DBSnapshotBase

logger = logging.getLogger(__name__)


@dataclass
class SnapshotInfo:
    """Snapshot metadata."""

    snapshot_id: str  # Unique ID (timestamp_reason_slug)
    snapshot_path: Path
    source_db_path: Path
    timestamp: str  # YYYYMMDD_HHMMSS
    reason: str
    tags: list[str]
    size_bytes: int
    sha256: str | None = None


class SnapshotService(DBSnapshotBase):
    """Service for creating and managing DB snapshots."""

    def __init__(self, storage_dir: Path | None = None):
        """
        Initialize snapshot service.

        Args:
            storage_dir: Where to store snapshots (default: %LOCALAPPDATA%/HDLE/snapshots/)
        """
        if storage_dir is None:
            storage_dir = ResourcePaths.resolve_data_root(create=True) / "snapshots"

        self.storage_dir = storage_dir
        self._ensure_directory(self.storage_dir)
        logger.info(f"SnapshotService initialized: {self.storage_dir}")

    def create_snapshot(
        self,
        source_db_path: Path,
        reason: str,
        tags: list[str] | None = None,
        compute_hash: bool = True,
    ) -> SnapshotInfo:
        """
        Create WAL-safe snapshot.

        Args:
            source_db_path: Source database file
            reason: Human-readable reason (e.g., "pre_golden_test", "manual_backup")
            tags: Optional tags for categorization
            compute_hash: Whether to compute SHA256 (slower but verifiable)

        Returns:
            SnapshotInfo with paths and metadata

        Raises:
            RuntimeError: If snapshot creation fails
            OSError: If file operations fail
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        reason_slug = reason.replace(" ", "_").lower()
        snapshot_id = f"{timestamp}_{reason_slug}"

        snapshot_path = self.storage_dir / f"snapshot_{snapshot_id}.db"

        logger.info(f"Creating snapshot: {snapshot_path}")

        try:
            # Use shared base method (WAL-safe)
            self._create_snapshot_copy(source_db_path, snapshot_path)

            size_bytes = snapshot_path.stat().st_size

            # Optional SHA256
            sha256 = None
            if compute_hash:
                sha256 = self._compute_sha256(snapshot_path)
                logger.debug(f"Snapshot SHA256: {sha256[:16]}...")

            logger.info(f"Snapshot created: {snapshot_path} ({size_bytes} bytes)")

            return SnapshotInfo(
                snapshot_id=snapshot_id,
                snapshot_path=snapshot_path,
                source_db_path=source_db_path,
                timestamp=timestamp,
                reason=reason,
                tags=tags or [],
                size_bytes=size_bytes,
                sha256=sha256,
            )

        except Exception as e:
            # Clean up partial snapshot
            if snapshot_path.exists():
                try:
                    snapshot_path.unlink()
                except Exception:
                    pass

            logger.error(f"Snapshot creation failed: {e}")
            raise RuntimeError(f"Snapshot creation failed: {e}") from e

    def list_snapshots(self) -> list[SnapshotInfo]:
        """
        List all snapshots in storage directory.

        Returns:
            List of SnapshotInfo objects sorted by timestamp (newest first)
        """
        snapshots = []

        for snapshot_file in sorted(
            self.storage_dir.glob("snapshot_*.db"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        ):
            # Parse filename: snapshot_YYYYMMDD_HHMMSS_reason.db
            name = snapshot_file.stem  # Remove .db
            parts = name.split("_", 3)  # ["snapshot", "YYYYMMDD", "HHMMSS", "reason"]

            if len(parts) >= 4:
                timestamp = f"{parts[1]}_{parts[2]}"
                reason = parts[3].replace("_", " ")
            else:
                timestamp = "unknown"
                reason = "unknown"

            snapshots.append(
                SnapshotInfo(
                    snapshot_id=name.replace("snapshot_", ""),
                    snapshot_path=snapshot_file,
                    source_db_path=Path("unknown"),  # Not stored in filename
                    timestamp=timestamp,
                    reason=reason,
                    tags=[],
                    size_bytes=snapshot_file.stat().st_size,
                    sha256=None,
                )
            )

        logger.debug(f"Found {len(snapshots)} snapshots")
        return snapshots

    def delete_snapshot(self, snapshot_id: str) -> bool:
        """
        Delete snapshot by ID.

        Args:
            snapshot_id: Snapshot ID (from SnapshotInfo)

        Returns:
            True if deleted, False if not found
        """
        snapshot_path = self.storage_dir / f"snapshot_{snapshot_id}.db"

        if snapshot_path.exists():
            try:
                snapshot_path.unlink()
                logger.info(f"Deleted snapshot: {snapshot_id}")
                return True
            except Exception as e:
                logger.error(f"Failed to delete snapshot {snapshot_id}: {e}")
                raise

        logger.warning(f"Snapshot not found: {snapshot_id}")
        return False

    def get_snapshot(self, snapshot_id: str) -> SnapshotInfo | None:
        """
        Get snapshot metadata by ID.

        Args:
            snapshot_id: Snapshot ID

        Returns:
            SnapshotInfo if found, None otherwise
        """
        snapshot_path = self.storage_dir / f"snapshot_{snapshot_id}.db"

        if not snapshot_path.exists():
            return None

        # Parse filename
        name = snapshot_path.stem
        parts = name.split("_", 3)

        if len(parts) >= 4:
            timestamp = f"{parts[1]}_{parts[2]}"
            reason = parts[3].replace("_", " ")
        else:
            timestamp = "unknown"
            reason = "unknown"

        return SnapshotInfo(
            snapshot_id=snapshot_id,
            snapshot_path=snapshot_path,
            source_db_path=Path("unknown"),
            timestamp=timestamp,
            reason=reason,
            tags=[],
            size_bytes=snapshot_path.stat().st_size,
            sha256=None,
        )
