"""Audio provider settings dialog (focused on local MMS provider)."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from app.infra.settings import SettingsService
from app.ui.dialogs.mms_license_gate_dialog import MMS_LICENSE_ACCEPTED_KEY, ensure_mms_license_accepted


class AudioProviderSettingsDialog(QDialog):
    """Minimal-risk settings UI for local MMS provider."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = SettingsService.get_instance()
        self.setWindowTitle("Audio Provider Settings")
        self.setMinimumWidth(620)
        self._init_ui()
        self._load()

    def _init_ui(self):
        root = QVBoxLayout(self)
        title = QLabel("<b>Audio Provider Settings</b><br>Configure optional local provider (MMS).")
        title.setWordWrap(True)
        root.addWidget(title)

        form = QFormLayout()

        self.mms_enabled = QCheckBox("Enable mms_tts_local")
        form.addRow("Local provider:", self.mms_enabled)

        self.license_state = QLabel("")
        form.addRow("License gate:", self.license_state)

        self.model_path = QLineEdit()
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_model_path)
        model_row = QHBoxLayout()
        model_row.addWidget(self.model_path, 1)
        model_row.addWidget(browse_btn)
        form.addRow("Model path:", model_row)

        self.review_license_btn = QPushButton("Review / Accept MMS License Gate")
        self.review_license_btn.clicked.connect(self._review_license)
        form.addRow("", self.review_license_btn)

        root.addLayout(form)

        hint = QLabel(
            "Notes:\n"
            "- Base installer does not bundle model weights.\n"
            "- Configure an external local model path for offline mode.\n"
            "- Without license acceptance, mms_tts_local remains blocked."
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _load(self):
        self.mms_enabled.setChecked(self.settings.get_bool("audio/providers/mms_tts_local/enabled", False))
        self.model_path.setText(self.settings.get_string("audio/providers/mms_tts_local/model_path", ""))
        self._refresh_license_state()

    def _refresh_license_state(self):
        accepted = self.settings.get_bool(MMS_LICENSE_ACCEPTED_KEY, False)
        self.license_state.setText("Accepted" if accepted else "Not accepted")
        self.license_state.setStyleSheet("color: #2e7d32;" if accepted else "color: #d32f2f;")

    def _browse_model_path(self):
        selected = QFileDialog.getExistingDirectory(self, "Select MMS Model Directory")
        if selected:
            self.model_path.setText(selected)

    def _review_license(self):
        if ensure_mms_license_accepted(parent=self):
            self._refresh_license_state()
            QMessageBox.information(self, "License Gate", "License gate accepted.")

    def accept(self):
        self.settings.set_value("audio/providers/mms_tts_local/enabled", self.mms_enabled.isChecked())
        self.settings.set_value("audio/providers/mms_tts_local/model_path", self.model_path.text().strip())
        self.settings.sync()
        super().accept()


def show_audio_provider_settings(*, parent=None) -> bool:
    """Show dialog. Returns True if saved."""
    dialog = AudioProviderSettingsDialog(parent=parent)
    return dialog.exec() == QDialog.DialogCode.Accepted
