"""Operations status widget for the main window status bar (PERF-SCALE PATCH-B).

Displays a compact indicator of active heavy background operations.
Subscribes to OperationsCenter signals; updates itself on the main thread.

Layout:
  [⚙ 2 ops]   — when operations are active (amber text)
  (hidden)     — when idle
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel

from app.services.operations_center import OperationsCenter


class OperationsStatusWidget(QLabel):
    """Status-bar widget that reflects OperationsCenter activity."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setMinimumWidth(90)
        self._update(0)

        center = OperationsCenter.instance()
        center.active_count_changed.connect(self._update)

    # ------------------------------------------------------------------
    # Slot
    # ------------------------------------------------------------------

    def _update(self, count: int) -> None:
        if count == 0:
            self.setText("")
            self.setVisible(False)
        else:
            label = "op" if count == 1 else "ops"
            self.setText(f"⚙ {count} {label} active")
            self.setStyleSheet("color: #CC8800; font-weight: bold;")
            self.setVisible(True)
            self.setToolTip(self._build_tooltip())

    def _build_tooltip(self) -> str:
        ops = OperationsCenter.instance().active_ops()
        if not ops:
            return ""
        lines = [f"Active operations ({len(ops)}):"]
        for op in ops:
            lines.append(f"  • [{op.category}] {op.name}")
        return "\n".join(lines)
