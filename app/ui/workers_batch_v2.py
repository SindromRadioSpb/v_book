"""Batch Translate Worker V2 - PATCH-02.

New async worker for batch translation using BatchTranslateEngineV2.

Key improvements:
- Fully async (QThread-based)
- Real progress stages: "Starting worker...", "Translating...", "Writing..."
- Graceful cancellation
- Error boundary with user-friendly messages
- Selection preservation support (stores entity_ids)
"""

import logging

from PyQt6.QtCore import QThread, pyqtSignal

from app.services.batch_translate_engine_v2 import (
    BatchTranslateEngineV2,
    BatchTranslateItem,
    BatchTranslateOptions,
)
from app.services.db_service import DBService

logger = logging.getLogger(__name__)


class BatchTranslateWorkerV2(QThread):
    """V2 worker for batch translation with improved reliability."""

    # Signals
    progress = pyqtSignal(int, int)  # (completed, total)
    stage_changed = pyqtSignal(str)  # Stage description
    finished = pyqtSignal(object)  # BatchResult
    error = pyqtSignal(str)  # Error message

    def __init__(
        self,
        items: list[BatchTranslateItem],
        options: BatchTranslateOptions,
        tab_type: str,
    ):
        """Initialize worker.

        Args:
            items: List of items to translate
            options: Batch translate options
            tab_type: Tab identifier for logging ("dictionary" | "terms" | "tm")
        """
        super().__init__()
        self.items = items
        self.options = options
        self.tab_type = tab_type
        self._cancel_requested = False

    def run(self):
        """Execute batch translation in background thread."""
        try:
            logger.info(
                f"BatchWorkerV2 started: tab={self.tab_type}, "
                f"items={len(self.items)}, provider_mode={self.options.provider_mode}"
            )

            # Stage 1: Initialize engine
            self.stage_changed.emit("Initializing translation engine...")
            engine = BatchTranslateEngineV2()
            db_service = DBService.get_instance()

            # Stage 2: Execute translation
            self.stage_changed.emit("Translating...")
            with db_service.get_session() as session:
                result = engine.execute(
                    session=session,
                    items=self.items,
                    options=self.options,
                    progress_callback=self._on_progress,
                    cancel_check=lambda: self._cancel_requested,
                )

                # Stage 3: Finalizing
                self.stage_changed.emit("Finalizing...")

                # Emit result
                self.finished.emit(result)

                logger.info(
                    f"BatchWorkerV2 finished: succeeded={result.succeeded}, "
                    f"skipped={result.skipped}, failed={result.failed}"
                )

        except Exception as e:
            logger.exception("BatchWorkerV2 failed")
            error_msg = self._make_user_friendly_error(str(e))
            self.error.emit(error_msg)

    def cancel(self):
        """Request graceful cancellation."""
        logger.info("BatchWorkerV2 cancel requested")
        self._cancel_requested = True

    def _on_progress(self, completed: int, total: int):
        """Handle progress callback from engine."""
        self.progress.emit(completed, total)

    def _make_user_friendly_error(self, error: str) -> str:
        """Convert technical error to user-friendly message."""
        error_lower = error.lower()

        if "database" in error_lower or "locked" in error_lower:
            return (
                "Database error occurred during batch translation.\n\n"
                "Please try again. If the problem persists, restart the application."
            )
        elif "provider" in error_lower or "not found" in error_lower:
            return (
                "MT provider error occurred.\n\n"
                "Check:\n"
                "- MT providers enabled in Settings (Ctrl+Alt+P)\n"
                "- Local model installed (if using Local MT)\n"
                "- Network connection (if using cloud providers)"
            )
        elif "worker" in error_lower or "timeout" in error_lower:
            return (
                "MT worker timeout or startup error.\n\n"
                "This can happen if:\n"
                "- First-time model loading (wait ~30s and retry)\n"
                "- System resources low (close other apps)\n"
                "- Model files corrupted (reinstall model)"
            )
        elif "normalization" in error_lower:
            return (
                "Text normalization error.\n\n"
                "Some selected text contains invalid characters or format.\n"
                "Try selecting different rows."
            )
        else:
            return f"Unexpected error:\n\n{error}\n\nPlease check logs for details."
