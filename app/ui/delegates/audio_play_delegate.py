"""Audio play delegate for table cells (no setIndexWidget per-row)."""

from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import QEvent, QModelIndex, QRect, Qt
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import QApplication, QStyle, QStyleOptionButton, QStyledItemDelegate


class AudioPlayDelegate(QStyledItemDelegate):
    """Draws a compact play button in an audio-status cell."""

    def __init__(
        self,
        parent=None,
        *,
        on_play_clicked: Optional[Callable[[QModelIndex], None]] = None,
    ):
        super().__init__(parent)
        self._on_play_clicked = on_play_clicked

    @staticmethod
    def _is_ready(index: QModelIndex) -> bool:
        status = str(index.data(Qt.ItemDataRole.DisplayRole) or "").strip().lower()
        return status == "ready"

    @staticmethod
    def _button_rect(cell_rect: QRect) -> QRect:
        width = min(48, max(32, cell_rect.width() - 8))
        height = min(22, max(16, cell_rect.height() - 6))
        x = cell_rect.x() + (cell_rect.width() - width) // 2
        y = cell_rect.y() + (cell_rect.height() - height) // 2
        return QRect(x, y, width, height)

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        if not index.isValid():
            return
        if not self._is_ready(index):
            super().paint(painter, option, index)
            return

        btn_rect = self._button_rect(option.rect)
        button = QStyleOptionButton()
        button.rect = btn_rect
        button.state = QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_Raised
        button.text = ""
        style = option.widget.style() if option.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_PushButton, button, painter)

        icon = style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
        icon_rect = QRect(btn_rect.x() + 12, btn_rect.y() + 4, 14, 14)
        icon.paint(painter, icon_rect, Qt.AlignmentFlag.AlignCenter)

    def editorEvent(self, event, model, option, index: QModelIndex) -> bool:
        if not index.isValid() or not self._is_ready(index):
            return super().editorEvent(event, model, option, index)

        event_type = event.type()
        if event_type == QEvent.Type.MouseButtonRelease:
            if self._button_rect(option.rect).contains(event.pos()):  # type: ignore[attr-defined]
                if self._on_play_clicked:
                    self._on_play_clicked(index)
                return True
        return super().editorEvent(event, model, option, index)
