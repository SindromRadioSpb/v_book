"""Batch Translate Dialog - PATCH-UI-BATCH-T02.

Confirm dialog for batch translation with provider and write mode selection.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QRadioButton, QComboBox, QButtonGroup, QGroupBox, QCheckBox
)
from PyQt6.QtCore import Qt

from app.infra.settings import SettingsService


class BatchTranslateDialog(QDialog):
    """Confirm dialog for batch translation.

    Allows user to select:
    - Provider mode: chain (default) or force specific provider
    - Write mode: fill empty (default), overwrite, skip non-empty
    - Remember choices checkbox
    """

    def __init__(self, parent=None, selected_count: int = 0):
        """Initialize dialog.

        Args:
            parent: Parent widget
            selected_count: Number of selected rows
        """
        super().__init__(parent)
        self.selected_count = selected_count
        self.settings = SettingsService.get_instance()
        self.init_ui()
        self.load_settings()

    def init_ui(self):
        """Initialize UI."""
        self.setWindowTitle("Batch Translate Selected Rows")
        self.setMinimumWidth(450)

        layout = QVBoxLayout()

        # Header
        header = QLabel(f"<b>Selected rows:</b> {self.selected_count}")
        header.setStyleSheet("font-size: 13px; padding: 8px;")
        layout.addWidget(header)

        # Provider mode group
        provider_group = QGroupBox("Provider Mode")
        provider_layout = QVBoxLayout()

        self.provider_button_group = QButtonGroup(self)

        self.chain_radio = QRadioButton("Use provider chain (recommended)")
        self.chain_radio.setChecked(True)
        self.provider_button_group.addButton(self.chain_radio, 0)
        provider_layout.addWidget(self.chain_radio)

        # Force provider option
        force_layout = QHBoxLayout()
        self.force_radio = QRadioButton("Force provider:")
        self.provider_button_group.addButton(self.force_radio, 1)
        force_layout.addWidget(self.force_radio)

        self.provider_combo = QComboBox()
        self.provider_combo.addItems([
            "google_translate",
            "local_nllb",
            "deepl",
            "microsoft",
            "libretranslate",
        ])
        self.provider_combo.setEnabled(False)
        force_layout.addWidget(self.provider_combo)
        force_layout.addStretch()

        provider_layout.addLayout(force_layout)

        # Enable combo when force radio selected
        self.force_radio.toggled.connect(self.provider_combo.setEnabled)

        provider_group.setLayout(provider_layout)
        layout.addWidget(provider_group)

        # Write mode group
        write_group = QGroupBox("Write Mode")
        write_layout = QVBoxLayout()

        self.write_button_group = QButtonGroup(self)

        self.fill_empty_radio = QRadioButton("Fill empty only (recommended)")
        self.fill_empty_radio.setChecked(True)
        self.write_button_group.addButton(self.fill_empty_radio, 0)
        write_layout.addWidget(self.fill_empty_radio)

        self.overwrite_radio = QRadioButton("Overwrite existing translations")
        self.write_button_group.addButton(self.overwrite_radio, 1)
        write_layout.addWidget(self.overwrite_radio)

        self.skip_radio = QRadioButton("Skip non-empty (no changes)")
        self.write_button_group.addButton(self.skip_radio, 2)
        write_layout.addWidget(self.skip_radio)

        write_group.setLayout(write_layout)
        layout.addWidget(write_group)

        # Remember checkbox
        self.remember_checkbox = QCheckBox("Remember my choices")
        self.remember_checkbox.setChecked(True)
        layout.addWidget(self.remember_checkbox)

        # Buttons
        button_layout = QHBoxLayout()

        settings_btn = QPushButton("Settings...")
        settings_btn.clicked.connect(self.open_settings)
        button_layout.addWidget(settings_btn)

        button_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        self.translate_btn = QPushButton("Translate")
        self.translate_btn.setDefault(True)
        self.translate_btn.setStyleSheet(
            "QPushButton { background-color: #4caf50; color: white; padding: 6px 16px; font-weight: bold; }"
        )
        self.translate_btn.clicked.connect(self.accept)
        button_layout.addWidget(self.translate_btn)

        layout.addLayout(button_layout)

        self.setLayout(layout)

    def load_settings(self):
        """Load saved settings."""
        # Provider mode
        provider_mode = self.settings.get_string("batch_translate/provider_mode", "chain")
        if provider_mode == "chain":
            self.chain_radio.setChecked(True)
        else:
            self.force_radio.setChecked(True)
            # Extract provider from "force:provider_id"
            if provider_mode.startswith("force:"):
                provider_id = provider_mode.split(":", 1)[1]
                index = self.provider_combo.findText(provider_id)
                if index >= 0:
                    self.provider_combo.setCurrentIndex(index)

        # Write mode
        write_mode = self.settings.get_string("batch_translate/write_mode", "FILL_EMPTY")
        if write_mode == "FILL_EMPTY":
            self.fill_empty_radio.setChecked(True)
        elif write_mode == "OVERWRITE":
            self.overwrite_radio.setChecked(True)
        elif write_mode == "SKIP_NON_EMPTY":
            self.skip_radio.setChecked(True)

        # Remember checkbox
        remember = self.settings.get_bool("batch_translate/remember_choices", True)
        self.remember_checkbox.setChecked(remember)

    def save_settings(self):
        """Save settings if remember is checked."""
        if not self.remember_checkbox.isChecked():
            return

        # Provider mode
        provider_mode = self.get_provider_mode()
        self.settings.set_value("batch_translate/provider_mode", provider_mode)

        # Write mode
        write_mode = self.get_write_mode()
        self.settings.set_value("batch_translate/write_mode", write_mode)

        # Remember choice itself
        self.settings.set_value("batch_translate/remember_choices", True)

    def get_provider_mode(self) -> str:
        """Get selected provider mode.

        Returns:
            "chain" or "force:<provider_id>"
        """
        if self.chain_radio.isChecked():
            return "chain"
        else:
            provider_id = self.provider_combo.currentText()
            return f"force:{provider_id}"

    def get_write_mode(self) -> str:
        """Get selected write mode.

        Returns:
            "FILL_EMPTY", "OVERWRITE", or "SKIP_NON_EMPTY"
        """
        if self.fill_empty_radio.isChecked():
            return "FILL_EMPTY"
        elif self.overwrite_radio.isChecked():
            return "OVERWRITE"
        elif self.skip_radio.isChecked():
            return "SKIP_NON_EMPTY"
        else:
            return "FILL_EMPTY"  # Default

    def open_settings(self):
        """Open MT provider settings dialog."""
        from app.ui.provider_settings_dialog import show_provider_settings
        show_provider_settings(parent=self)

    def accept(self):
        """Handle accept - save settings and close."""
        self.save_settings()
        super().accept()


def show_batch_translate_dialog(parent=None, selected_count: int = 0) -> tuple[bool, str, str]:
    """Show batch translate dialog and return user choices.

    Args:
        parent: Parent widget
        selected_count: Number of selected rows

    Returns:
        Tuple of (accepted, provider_mode, write_mode)
        - accepted: True if user clicked Translate, False if cancelled
        - provider_mode: "chain" or "force:<provider_id>"
        - write_mode: "FILL_EMPTY", "OVERWRITE", or "SKIP_NON_EMPTY"
    """
    dialog = BatchTranslateDialog(parent, selected_count)
    result = dialog.exec()

    if result == QDialog.DialogCode.Accepted:
        return True, dialog.get_provider_mode(), dialog.get_write_mode()
    else:
        return False, "chain", "FILL_EMPTY"
