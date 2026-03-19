"""Pipeline stage throttler.

Advisory guard that prevents multiple heavy pipeline operations from starting
concurrently in the common UI path. The hard mutex lives in OperationsCenter;
this class only provides pre-start warnings and tooltips.
"""

from __future__ import annotations

import logging
from typing import ClassVar

logger = logging.getLogger(__name__)

try:
    from PyQt6.QtWidgets import QMessageBox, QWidget

    _HAS_PYQT = True
except ImportError:  # pragma: no cover
    _HAS_PYQT = False

from app.services.operations_center import HEAVY_CATEGORIES, OperationsCenter


class PipelineThrottler:
    """Advisory throttler for heavy pipeline operations."""

    _instance: ClassVar[PipelineThrottler | None] = None

    @classmethod
    def instance(cls) -> PipelineThrottler:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_for_tests(cls) -> None:
        cls._instance = None

    def is_slot_free(self, category: str) -> bool:
        """Return True if a new operation of this category may start."""
        return OperationsCenter.instance().is_slot_available(category)

    def check_and_warn(
        self,
        category: str,
        parent: object | None = None,
        operation_label: str = "",
    ) -> bool:
        """Check whether the slot is free; show a warning dialog if not."""
        if self.is_slot_free(category):
            return True

        active = OperationsCenter.instance().blocking_ops(category)
        running_names = "\n".join(f"  - {op.name}" for op in active)
        op_display = operation_label or category.replace("_", " ").title()
        is_heavy = category in HEAVY_CATEGORIES

        if is_heavy:
            header = "another heavy operation is already running"
            detail = "Only one heavy write-oriented operation can run at a time."
        else:
            header = "another operation of this type is already running"
            detail = "Please wait for it to finish before starting a new one."

        message = (
            f"Cannot start '{op_display}' - {header}:\n\n"
            f"{running_names}\n\n"
            f"{detail}\n\n"
            "Tip: The status bar shows active operations."
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
        active = OperationsCenter.instance().blocking_ops(category)
        if not active:
            return ""
        return f"Busy: {active[0].name}"
