"""File system watcher (placeholder for M2+)."""

import logging
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)


class FolderWatcher:
    """Watches a folder for changes (to be implemented in M2)."""

    def __init__(self, folder_path: Path, callback: Callable):
        self.folder_path = folder_path
        self.callback = callback
        self.running = False
        logger.info(f"FolderWatcher created for {folder_path}")

    def start(self) -> None:
        """Start watching (not implemented yet)."""
        self.running = True
        logger.warning("FolderWatcher.start() not implemented yet")

    def stop(self) -> None:
        """Stop watching."""
        self.running = False
        logger.info("FolderWatcher stopped")
