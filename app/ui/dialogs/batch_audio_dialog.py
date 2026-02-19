"""Batch Audio Dialog for source-only audio generation."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from app.infra.settings import SettingsService
from app.services.audio_generation_service import list_available_audio_providers


class BatchAudioDialog(QDialog):
    """Confirm dialog for batch audio generation."""

    def __init__(self, parent=None, selected_count: int = 0, scope_enabled: bool = False, filtered_count: int = 0):
        super().__init__(parent)
        self.selected_count = selected_count
        self.scope_enabled = scope_enabled
        self.filtered_count = filtered_count
        self.settings = SettingsService.get_instance()
        self._init_ui()
        self._load_settings()

    def _init_ui(self):
        self.setWindowTitle("Batch Generate Source Audio")
        self.setMinimumWidth(470)
        layout = QVBoxLayout(self)

        header = QLabel(f"<b>Selected rows:</b> {self.selected_count}")
        header.setStyleSheet("font-size: 13px; padding: 8px;")
        layout.addWidget(header)

        if self.scope_enabled:
            scope_group = QGroupBox("Scope")
            scope_layout = QVBoxLayout()
            self.scope_group = QButtonGroup(self)
            self.current_page_radio = QRadioButton(f"Current page ({self.selected_count} selected)")
            self.current_page_radio.setChecked(True)
            self.scope_group.addButton(self.current_page_radio, 0)
            scope_layout.addWidget(self.current_page_radio)

            self.all_pages_radio = QRadioButton("All pages (filtered)")
            self.scope_group.addButton(self.all_pages_radio, 1)
            scope_layout.addWidget(self.all_pages_radio)

            count_label = QLabel(f"   -> Will process ~{self.filtered_count} rows matching current filters")
            count_label.setStyleSheet("color: #666; font-size: 11px; padding-left: 20px;")
            scope_layout.addWidget(count_label)
            scope_group.setLayout(scope_layout)
            layout.addWidget(scope_group)

        provider_group = QGroupBox("Provider Mode")
        provider_layout = QVBoxLayout()
        self.provider_group = QButtonGroup(self)
        self.chain_radio = QRadioButton("Use provider chain (recommended)")
        self.chain_radio.setChecked(True)
        self.provider_group.addButton(self.chain_radio, 0)
        provider_layout.addWidget(self.chain_radio)

        force_row = QHBoxLayout()
        self.force_radio = QRadioButton("Force provider:")
        self.provider_group.addButton(self.force_radio, 1)
        force_row.addWidget(self.force_radio)
        self.provider_combo = QComboBox()
        providers = list_available_audio_providers()
        self.provider_combo.addItems(providers or ["mock_local_audio"])
        self.provider_combo.setEnabled(False)
        force_row.addWidget(self.provider_combo)
        force_row.addStretch()
        provider_layout.addLayout(force_row)
        self.force_radio.toggled.connect(self.provider_combo.setEnabled)
        provider_group.setLayout(provider_layout)
        layout.addWidget(provider_group)

        write_group = QGroupBox("Write Mode")
        write_layout = QVBoxLayout()
        self.write_group = QButtonGroup(self)
        self.missing_only_radio = QRadioButton("Generate only where audio is missing (recommended)")
        self.missing_only_radio.setChecked(True)
        self.write_group.addButton(self.missing_only_radio, 0)
        write_layout.addWidget(self.missing_only_radio)
        self.regenerate_radio = QRadioButton("Regenerate even when audio already exists")
        self.write_group.addButton(self.regenerate_radio, 1)
        write_layout.addWidget(self.regenerate_radio)
        write_group.setLayout(write_layout)
        layout.addWidget(write_group)

        self.remember_checkbox = QCheckBox("Remember my choices")
        self.remember_checkbox.setChecked(True)
        layout.addWidget(self.remember_checkbox)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)
        run_btn = QPushButton("Generate Audio")
        run_btn.setDefault(True)
        run_btn.setStyleSheet(
            "QPushButton { background-color: #1976d2; color: white; padding: 6px 16px; font-weight: bold; }"
        )
        run_btn.clicked.connect(self.accept)
        buttons.addWidget(run_btn)
        layout.addLayout(buttons)

    def _load_settings(self):
        provider_mode = self.settings.get_string("batch_audio/provider_mode", "chain")
        if provider_mode == "chain":
            self.chain_radio.setChecked(True)
        elif provider_mode.startswith("force:"):
            self.force_radio.setChecked(True)
            provider_id = provider_mode.split(":", 1)[1]
            idx = self.provider_combo.findText(provider_id)
            if idx >= 0:
                self.provider_combo.setCurrentIndex(idx)

        write_mode = self.settings.get_string("batch_audio/write_mode", "MISSING_ONLY")
        if write_mode == "REGENERATE_ALL":
            self.regenerate_radio.setChecked(True)
        else:
            self.missing_only_radio.setChecked(True)

        remember = self.settings.get_bool("batch_audio/remember_choices", True)
        self.remember_checkbox.setChecked(remember)

    def _save_settings(self):
        if not self.remember_checkbox.isChecked():
            return
        self.settings.set_value("batch_audio/provider_mode", self.get_provider_mode())
        self.settings.set_value("batch_audio/write_mode", self.get_write_mode())
        self.settings.set_value("batch_audio/remember_choices", True)

    def get_provider_mode(self) -> str:
        if self.chain_radio.isChecked():
            return "chain"
        return f"force:{self.provider_combo.currentText()}"

    def get_write_mode(self) -> str:
        if self.regenerate_radio.isChecked():
            return "REGENERATE_ALL"
        return "MISSING_ONLY"

    def get_scope(self) -> str:
        if not self.scope_enabled:
            return "current_page"
        if self.all_pages_radio.isChecked():
            return "all_filtered"
        return "current_page"

    def accept(self):
        self._save_settings()
        super().accept()


def show_batch_audio_dialog(
    *,
    parent=None,
    selected_count: int = 0,
    scope_enabled: bool = False,
    filtered_count: int = 0,
):
    """Show batch audio dialog and return normalized options tuple."""
    dialog = BatchAudioDialog(
        parent=parent,
        selected_count=selected_count,
        scope_enabled=scope_enabled,
        filtered_count=filtered_count,
    )
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    if not accepted:
        return False, "chain", "MISSING_ONLY", "current_page"
    return True, dialog.get_provider_mode(), dialog.get_write_mode(), dialog.get_scope()
