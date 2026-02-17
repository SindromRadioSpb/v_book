"""Shared table header layout controller for premium column UX."""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QAbstractItemView, QHeaderView, QMenu, QTableWidget

from app.infra.settings import SettingsService

logger = logging.getLogger(__name__)


class TableLayoutController:
    """Manages table column resize/reorder persistence with safe restore."""

    def __init__(
        self,
        settings: SettingsService,
        table_id: str,
        table: QAbstractItemView,
        default_widths: Optional[dict[int, int]] = None,
        minimum_section_width: int = 60,
        save_debounce_ms: int = 400,
    ):
        self.settings = settings
        self.table_id = table_id
        self.table = table
        self.header: QHeaderView = table.horizontalHeader()
        self.default_widths = default_widths or {}
        self.minimum_section_width = minimum_section_width
        self._signature_key = f"table/{self.table_id}/header_signature"
        self._is_applying = False

        self._save_timer = QTimer(self.header)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(save_debounce_ms)
        self._save_timer.timeout.connect(self.save_now)

    def install(self) -> bool:
        """Install controller behavior and restore saved state if valid."""
        self.header.setMinimumSectionSize(self.minimum_section_width)
        self.header.setSectionsMovable(True)
        self.header.setStretchLastSection(False)

        self._set_interactive_resize_mode()

        restored = self.restore()
        if not restored:
            self.reset_to_defaults(save=False)

        self.header.sectionMoved.connect(self._on_header_changed)
        self.header.sectionResized.connect(self._on_header_changed)
        self.header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.header.customContextMenuRequested.connect(self._show_header_menu)
        return restored

    def restore(self) -> bool:
        """Restore header state only when saved schema matches current schema."""
        if not self._is_signature_compatible():
            logger.info(f"Header state skipped for '{self.table_id}' due to schema mismatch")
            return False

        self._is_applying = True
        try:
            return self.settings.restore_header_state(self.table_id, self.header)
        finally:
            self._is_applying = False

    def reset_to_defaults(self, save: bool = True) -> None:
        """Reset column widths to default values."""
        self._is_applying = True
        try:
            self._set_interactive_resize_mode()
            for col, width in sorted(self.default_widths.items()):
                if 0 <= col < self._column_count():
                    self.table.setColumnWidth(col, width)
        finally:
            self._is_applying = False

        if save:
            self.save_now()

    def save_now(self) -> None:
        """Persist current header state and schema signature."""
        try:
            self.settings.save_header_state(self.table_id, self.header)
            self.settings.set_json(self._signature_key, self._build_signature())
        except Exception as e:
            logger.warning(f"Failed to save table layout '{self.table_id}': {e}")

    def _on_header_changed(self, *_args) -> None:
        """Debounced save for resize/reorder events."""
        if self._is_applying:
            return
        self._save_timer.start()

    def _show_header_menu(self, pos) -> None:
        """Show header menu with reset action."""
        menu = QMenu(self.header)
        reset_action = menu.addAction("Reset Columns Layout")
        chosen = menu.exec(self.header.viewport().mapToGlobal(pos))
        if chosen == reset_action:
            self.reset_to_defaults(save=True)

    def _set_interactive_resize_mode(self) -> None:
        col_count = self._column_count()
        for col in range(col_count):
            self.header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)

    def _is_signature_compatible(self) -> bool:
        saved_signature = self.settings.get_json(self._signature_key, None)
        if not saved_signature:
            return True  # Backward-compatible: allow pre-signature state restore.
        return saved_signature == self._build_signature()

    def _build_signature(self) -> dict:
        return {
            "column_count": self._column_count(),
            "headers": self._normalized_headers(),
        }

    def _column_count(self) -> int:
        model = self.table.model()
        if model is None:
            return 0
        return model.columnCount()

    def _normalized_headers(self) -> list[str]:
        model = self.table.model()
        if model is None:
            return []

        headers: list[str] = []
        for col in range(model.columnCount()):
            label = model.headerData(
                col,
                Qt.Orientation.Horizontal,
                Qt.ItemDataRole.DisplayRole,
            )
            if label is None and isinstance(self.table, QTableWidget):
                item = self.table.horizontalHeaderItem(col)
                label = item.text() if item else ""
            text = str(label or "")
            headers.append(text.replace(" ▲", "").replace(" ▼", "").strip())
        return headers
