"""Reference setup state management."""

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Optional


class SetupStage(str, Enum):
    """Stages of reference corpus setup."""

    NOT_STARTED = "not_started"
    DOWNLOADING = "downloading"
    VERIFYING = "verifying"
    DECOMPRESSING = "decompressing"
    INSTALLING = "installing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class SetupState:
    """State of reference corpus setup process."""

    stage: SetupStage = SetupStage.NOT_STARTED
    mode: str = "download"  # "download" or "local_process"

    # Download progress
    bytes_downloaded: int = 0
    total_bytes: int = 0
    download_speed_bps: float = 0.0  # bytes per second

    # Processing progress (for local_process mode)
    docs_processed: int = 0
    total_docs: int = 0

    # Timestamps
    started_at: str | None = None
    completed_at: str | None = None
    last_updated_at: str | None = None

    # Error handling
    error_message: str | None = None
    retry_count: int = 0

    # Checkpoints (for resume)
    last_checkpoint: str | None = None  # JSON serialized checkpoint data

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        data["stage"] = self.stage.value
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "SetupState":
        """Create from dictionary."""
        # Convert stage string to enum
        if "stage" in data and isinstance(data["stage"], str):
            data["stage"] = SetupStage(data["stage"])
        return cls(**data)

    def save_to_file(self, path: Path):
        """Save state to JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load_from_file(cls, path: Path) -> Optional["SetupState"]:
        """Load state from JSON file."""
        if not path.exists():
            return None

        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return cls.from_dict(data)
        except Exception:
            return None

    def update_progress(
        self,
        stage: SetupStage | None = None,
        bytes_downloaded: int | None = None,
        total_bytes: int | None = None,
        docs_processed: int | None = None,
        total_docs: int | None = None,
    ):
        """Update progress and timestamp."""
        if stage is not None:
            self.stage = stage

        if bytes_downloaded is not None:
            self.bytes_downloaded = bytes_downloaded

        if total_bytes is not None:
            self.total_bytes = total_bytes

        if docs_processed is not None:
            self.docs_processed = docs_processed

        if total_docs is not None:
            self.total_docs = total_docs

        self.last_updated_at = datetime.now(UTC).isoformat()

    def mark_started(self):
        """Mark setup as started."""
        self.started_at = datetime.now(UTC).isoformat()
        self.last_updated_at = self.started_at

    def mark_completed(self):
        """Mark setup as completed."""
        self.stage = SetupStage.COMPLETED
        self.completed_at = datetime.now(UTC).isoformat()
        self.last_updated_at = self.completed_at

    def mark_failed(self, error_message: str):
        """Mark setup as failed."""
        self.stage = SetupStage.FAILED
        self.error_message = error_message
        self.last_updated_at = datetime.now(UTC).isoformat()

    def mark_cancelled(self):
        """Mark setup as cancelled."""
        self.stage = SetupStage.CANCELLED
        self.last_updated_at = datetime.now(UTC).isoformat()

    def get_progress_percentage(self) -> float:
        """Get progress percentage (0-100)."""
        if self.mode == "download":
            if self.total_bytes == 0:
                return 0.0
            return (self.bytes_downloaded / self.total_bytes) * 100

        elif self.mode == "local_process":
            if self.total_docs == 0:
                return 0.0
            return (self.docs_processed / self.total_docs) * 100

        return 0.0

    def get_eta_seconds(self) -> float | None:
        """Get estimated time to completion in seconds."""
        if self.mode == "download" and self.download_speed_bps > 0:
            remaining_bytes = self.total_bytes - self.bytes_downloaded
            return remaining_bytes / self.download_speed_bps

        return None

    def can_resume(self) -> bool:
        """Check if setup can be resumed."""
        return self.stage in [
            SetupStage.DOWNLOADING,
            SetupStage.FAILED,
            SetupStage.CANCELLED,
        ]
