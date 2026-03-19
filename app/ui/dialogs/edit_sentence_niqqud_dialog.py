"""Dialog for manually editing (overriding) the niqqud for a single sentence."""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
)

logger = logging.getLogger(__name__)


class EditSentenceNiqqudDialog(QDialog):
    """Manual override dialog for one sentence_pronunciation row.

    Sets is_override=1, source='manual'.
    """

    def __init__(
        self,
        parent=None,
        *,
        sentence_id: int,
        sentence_text: str,
        current_niqqud: str | None = None,
    ):
        super().__init__(parent)
        self.sentence_id = sentence_id
        self.sentence_text = sentence_text
        self.setWindowTitle(f"Edit Sentence Niqqud — ID {sentence_id}")
        self.setMinimumWidth(540)
        self._changed = False
        self._init_ui(current_niqqud)

    def _init_ui(self, current_niqqud: str | None) -> None:
        layout = QVBoxLayout(self)

        # Source text (read-only)
        layout.addWidget(QLabel("<b>Sentence text:</b>"))
        src_lbl = QLabel(self.sentence_text)
        src_lbl.setWordWrap(True)
        src_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        src_lbl.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        src_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        layout.addWidget(src_lbl)

        layout.addSpacing(8)
        layout.addWidget(QLabel("<b>Niqqud override</b> (manual wins — never auto-overwritten):"))

        # Edit area
        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText("Enter niqqud text here…")
        if current_niqqud:
            self.edit.setPlainText(current_niqqud)
        self.edit.setMinimumHeight(80)
        self.edit.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        layout.addWidget(self.edit)

        # Preview label (RTL)
        layout.addWidget(QLabel("<b>Preview:</b>"))
        self._preview = QLabel("")
        self._preview.setWordWrap(True)
        self._preview.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._preview.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        self._preview.setStyleSheet(
            "font-size: 14px; color: #333; border: 1px solid #ccc; padding: 4px;"
        )
        layout.addWidget(self._preview)

        self.edit.textChanged.connect(self._update_preview)
        self._update_preview()

        # Buttons
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self._on_save)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _update_preview(self) -> None:
        text = self.edit.toPlainText()
        self._preview.setText(text or "<i>(empty)</i>")

    def _on_save(self) -> None:
        niqqud_text = self.edit.toPlainText().strip()
        try:
            from app.services.db_service import DBService
            from app.services.sentence_pronunciation_service import SentencePronunciationService

            db = DBService.get_instance()
            svc = SentencePronunciationService()
            with db.get_session() as session:
                svc.upsert_manual(
                    session,
                    sentence_id=self.sentence_id,
                    niqqud_text=niqqud_text,
                    notes="manual_override",
                )
                session.commit()
            self._changed = True
            self.accept()
        except Exception as exc:
            logger.error("Failed to save sentence niqqud: %s", exc, exc_info=True)
            QMessageBox.critical(self, "Save Error", f"Could not save niqqud:\n{exc}")

    def was_changed(self) -> bool:
        return self._changed


def show_edit_sentence_niqqud_dialog(
    parent=None,
    *,
    sentence_id: int,
    sentence_text: str,
    current_niqqud: str | None = None,
) -> bool:
    """Show dialog; return True if niqqud was saved."""
    dlg = EditSentenceNiqqudDialog(
        parent,
        sentence_id=sentence_id,
        sentence_text=sentence_text,
        current_niqqud=current_niqqud,
    )
    dlg.exec()
    return dlg.was_changed()
