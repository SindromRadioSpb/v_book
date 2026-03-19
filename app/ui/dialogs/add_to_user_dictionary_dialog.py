"""Dialog for adding selected rows to a user dictionary."""

from __future__ import annotations

import logging
from typing import Any

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from app.services.db_service import DBService
from app.services.user_dictionary_service import UserDictionaryService

logger = logging.getLogger(__name__)


class AddToUserDictionaryDialog(QDialog):
    """Select target dictionary and add options."""

    def __init__(
        self,
        *,
        selected_count: int,
        default_dictionary_id: int | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.selected_count = selected_count
        self.default_dictionary_id = default_dictionary_id
        self.db_service = DBService.get_instance()
        self.user_dict_service = UserDictionaryService()
        self.dictionaries = []
        self._load_dictionaries()
        self._init_ui()

    def _load_dictionaries(self) -> None:
        with self.db_service.get_session() as session:
            self.dictionaries = self.user_dict_service.list_dictionaries(session)

    def _init_ui(self) -> None:
        self.setWindowTitle("Add to User Dictionary")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)

        info = QLabel(f"Selected rows: {self.selected_count}")
        info.setStyleSheet("font-weight: bold;")
        layout.addWidget(info)

        row = QHBoxLayout()
        row.addWidget(QLabel("Dictionary:"))

        self.dictionary_combo = QComboBox()
        self._rebuild_dictionary_combo()
        row.addWidget(self.dictionary_combo, 1)

        self.new_dict_btn = QPushButton("New...")
        self.new_dict_btn.clicked.connect(self._on_create_dictionary)
        row.addWidget(self.new_dict_btn)
        layout.addLayout(row)

        self.skip_duplicates_checkbox = QCheckBox("Skip duplicates")
        self.skip_duplicates_checkbox.setChecked(True)
        layout.addWidget(self.skip_duplicates_checkbox)

        self.include_noise_checkbox = QCheckBox("Include noise rows")
        self.include_noise_checkbox.setChecked(False)
        layout.addWidget(self.include_noise_checkbox)

        self.preserve_origin_checkbox = QCheckBox("Preserve origin references")
        self.preserve_origin_checkbox.setChecked(True)
        layout.addWidget(self.preserve_origin_checkbox)

        tags_row = QHBoxLayout()
        tags_row.addWidget(QLabel("Tags (comma-separated):"))
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("e.g. review, deck-a")
        tags_row.addWidget(self.tags_edit, 1)
        layout.addLayout(tags_row)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #d32f2f;")
        layout.addWidget(self.error_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setText("Add")
        ok_btn.setDefault(True)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _rebuild_dictionary_combo(self) -> None:
        self.dictionary_combo.clear()
        for item in self.dictionaries:
            self.dictionary_combo.addItem(item.name, item.dictionary_id)

        if self.default_dictionary_id is not None:
            idx = self.dictionary_combo.findData(self.default_dictionary_id)
            if idx >= 0:
                self.dictionary_combo.setCurrentIndex(idx)

    def _on_create_dictionary(self) -> None:
        name, ok = QInputDialog.getText(self, "New Dictionary", "Dictionary name:")
        if not ok:
            return
        name = (name or "").strip()
        if not name:
            return

        try:
            with self.db_service.get_session() as session:
                dto = self.user_dict_service.create_dictionary(session, name=name)
                session.commit()
            self._load_dictionaries()
            self._rebuild_dictionary_combo()
            idx = self.dictionary_combo.findData(dto.dictionary_id)
            if idx >= 0:
                self.dictionary_combo.setCurrentIndex(idx)
        except Exception as e:
            QMessageBox.warning(self, "Create Dictionary Failed", str(e))

    def _on_accept(self) -> None:
        if self.dictionary_combo.count() == 0:
            self.error_label.setText("Create at least one dictionary first.")
            return
        self.accept()

    def selected_dictionary_id(self) -> int | None:
        return self.dictionary_combo.currentData()

    def options(self) -> dict[str, Any]:
        tags = [t.strip() for t in self.tags_edit.text().split(",") if t.strip()]
        return {
            "skip_duplicates": self.skip_duplicates_checkbox.isChecked(),
            "include_noise": self.include_noise_checkbox.isChecked(),
            "preserve_origin_refs": self.preserve_origin_checkbox.isChecked(),
            "tags": tags,
        }


def show_add_to_user_dictionary_dialog(
    *,
    parent=None,
    selected_count: int,
    default_dictionary_id: int | None = None,
) -> tuple[bool, int | None, dict[str, Any]]:
    """Show modal dialog and return user choice."""
    dialog = AddToUserDictionaryDialog(
        selected_count=selected_count,
        default_dictionary_id=default_dictionary_id,
        parent=parent,
    )
    result = dialog.exec()
    if result == QDialog.DialogCode.Accepted:
        return True, dialog.selected_dictionary_id(), dialog.options()
    return False, None, {}
