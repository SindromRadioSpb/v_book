"""Pipeline stage throttler — sequential-mode guard (PERF-SCALE PATCH-K).

Prevents multiple heavy pipeline operations (NLP process, ingest, term
extraction) from starting concurrently.  Uses OperationsCenter as the source
of truth for what is currently active.

The check is advisory and runs in the UI thread at worker dispatch time.
Workers already register with OperationsCenter when their run() starts, so
a brief race window exists (UI check → worker.start() → run() registers).
This is acceptable: the goal is to stop the common case of a user clicking
multiple heavy operations in quick succession, not to be a hard mutex.

Usage (in a UI handler before worker.start()):
    from app.services.pipeline_throttler import PipelineThrottler

    throttler = PipelineThrottler.instance()
    if not throttler.check_and_warn(category="nlp_process", parent=self):
        return  # another op is running; user was shown a message
    worker.start()
"""
from __future__ import annotations

import logging
from typing import ClassVar, Optional

logger = logging.getLogger(__name__)

try:
    from PyQt6.QtWidgets import QMessageBox, QWidget

    _HAS_PYQT = True
except ImportError:  # pragma: no cover
    _HAS_PYQT = False

from app.services.operations_center import HEAVY_CATEGORIES, OperationsCenter


class PipelineThrottler:
    """Advisory throttler for heavy pipeline operations.

    Singleton — call PipelineThrottler.instance().
    """

    _instance: ClassVar[Optional["PipelineThrottler"]] = None

    @classmethod
    def instance(cls) -> "PipelineThrottler":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_for_tests(cls) -> None:
        cls._instance = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_slot_free(self, category: str) -> bool:
        """Return True if a new operation of this category may start."""
        return OperationsCenter.instance().is_slot_available(category)

    def check_and_warn(
        self,
        category: str,
        parent: Optional[object] = None,
        operation_label: str = "",
    ) -> bool:
        """Check whether the slot is free; show a warning dialog if not.

        Args:
            category:        OperationsCenter category string (e.g. "nlp_process").
            parent:          Parent QWidget for the dialog (may be None).
            operation_label: Human-readable name for the attempted operation.

        Returns:
            True  → slot is free, caller may proceed with worker.start().
            False → slot is occupied, user was shown a blocking dialog.
        """
        if self.is_slot_free(category):
            return True

        # Build message listing what is currently running.
        active = [
            op for op in OperationsCenter.instance().active_ops()
            if op.category == category
        ]
        running_names = "\n".join(f"  • {op.name}" for op in active)
        op_display = operation_label or category.replace("_", " ").title()

        message = (
            f"Cannot start '{op_display}' — another operation of this type is already running:\n\n"
            f"{running_names}\n\n"
            "Please wait for it to finish before starting a new one.\n\n"
            "Tip: The status bar shows active operations (⚙ N ops active)."
        )

        logger.warning(
            "PipelineThrottler: blocked '%s' (%s); active: %s",
            op_display,
            category,
            [op.name for op in active],
        )

        if _HAS_PYQT and parent is not None:
            QMessageBox.warning(
                parent,  # type: ignore[arg-type]
                "Operation Already Running",
                message,
            )
        else:
            logger.warning("PipelineThrottler warning (no UI): %s", message)

        return False

    def format_blocked_reason(self, category: str) -> str:
        """Return a one-line reason string (for status labels / tooltips)."""
        active = [
            op for op in OperationsCenter.instance().active_ops()
            if op.category == category
        ]
        if not active:
            return ""
        return f"Busy: {active[0].name}"
