"""Provider Settings Dialog for MT rate limit configuration.

Allows users to configure:
- Rate limits per provider (requests per minute)
- Enable/disable providers
- Provider priority in chain
"""
from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QGroupBox,
    QLabel,
    QSpinBox,
    QCheckBox,
    QPushButton,
    QTabWidget,
    QWidget,
    QListWidget,
    QListWidgetItem,
    QDialogButtonBox,
    QMessageBox,
)


class ProviderSettingsDialog(QDialog):
    """Dialog for configuring MT provider settings."""

    # Provider registry with defaults
    PROVIDERS = {
        "deepl": {
            "name": "DeepL",
            "default_rate_limit": 60,
            "default_enabled": True,
        },
        "microsoft": {
            "name": "Microsoft Translator",
            "default_rate_limit": 60,
            "default_enabled": True,
        },
        "libretranslate": {
            "name": "LibreTranslate",
            "default_rate_limit": 60,
            "default_enabled": True,
        },
        "local_nllb": {
            "name": "Local NLLB (Offline)",
            "default_rate_limit": 9999,  # Unlimited for local
            "default_enabled": False,  # Disabled by default until model installed
        },
        "local_seamless": {
            "name": "Local Seamless M4T (Offline)",
            "default_rate_limit": 9999,  # Unlimited for local
            "default_enabled": False,  # Disabled by default until model installed
        },
    }

    def __init__(self, parent=None, settings=None):
        """Initialize provider settings dialog.

        Args:
            parent: Parent widget
            settings: QSettings instance (for testing)
        """
        super().__init__(parent)

        self.setWindowTitle("MT Provider Settings")
        self.setMinimumWidth(600)
        self.setMinimumHeight(500)

        self.settings = settings if settings is not None else QSettings()

        # Store widgets for each provider
        self.provider_widgets = {}

        self._init_ui()
        self._load_settings()

    def _init_ui(self):
        """Initialize UI components."""
        layout = QVBoxLayout(self)

        # Header
        header = QLabel("<h2>Machine Translation Provider Settings</h2>")
        layout.addWidget(header)

        info = QLabel(
            "Configure rate limits and enable/disable MT providers. "
            "Local providers offer unlimited offline translation."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        # Tabs
        tabs = QTabWidget()
        layout.addWidget(tabs)

        # Tab 1: Rate Limits
        rate_limits_tab = self._create_rate_limits_tab()
        tabs.addTab(rate_limits_tab, "Rate Limits")

        # Tab 2: Provider Chain
        chain_tab = self._create_chain_tab()
        tabs.addTab(chain_tab, "Provider Chain")

        # Buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        button_box.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(
            self._restore_defaults
        )
        layout.addWidget(button_box)

    def _create_rate_limits_tab(self) -> QWidget:
        """Create rate limits configuration tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Info
        info = QLabel(
            "Configure rate limits (requests per minute) for each provider. "
            "Lower values reduce API costs but increase translation time."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        # Create group box for each provider
        for provider_id, provider_info in self.PROVIDERS.items():
            group = QGroupBox(provider_info["name"])
            group_layout = QFormLayout(group)

            # Enable/disable checkbox
            enabled_cb = QCheckBox("Enabled")
            enabled_cb.setToolTip(f"Enable or disable {provider_info['name']} provider")

            # Rate limit spinbox
            rate_limit_spin = QSpinBox()
            rate_limit_spin.setMinimum(1)
            rate_limit_spin.setMaximum(10000)
            rate_limit_spin.setValue(provider_info["default_rate_limit"])
            rate_limit_spin.setSuffix(" req/min")
            rate_limit_spin.setToolTip(
                f"Maximum requests per minute for {provider_info['name']}"
            )

            # Add to layout
            group_layout.addRow("Status:", enabled_cb)
            group_layout.addRow("Rate Limit:", rate_limit_spin)

            # Store widgets
            self.provider_widgets[provider_id] = {
                "enabled": enabled_cb,
                "rate_limit": rate_limit_spin,
            }

            layout.addWidget(group)

        layout.addStretch()
        return widget

    def _create_chain_tab(self) -> QWidget:
        """Create provider chain configuration tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Info
        info = QLabel(
            "Configure the fallback order for MT providers. "
            "Providers are tried in order from top to bottom. "
            "Disabled providers are automatically skipped."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        # Chain list
        self.chain_list = QListWidget()
        self.chain_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        layout.addWidget(self.chain_list)

        # Populate chain list
        for provider_id, provider_info in self.PROVIDERS.items():
            item = QListWidgetItem(provider_info["name"])
            item.setData(Qt.ItemDataRole.UserRole, provider_id)
            self.chain_list.addItem(item)

        # Buttons
        button_layout = QHBoxLayout()
        move_up_btn = QPushButton("Move Up")
        move_up_btn.clicked.connect(self._move_up)
        move_down_btn = QPushButton("Move Down")
        move_down_btn.clicked.connect(self._move_down)

        button_layout.addWidget(move_up_btn)
        button_layout.addWidget(move_down_btn)
        button_layout.addStretch()

        layout.addLayout(button_layout)

        return widget

    def _move_up(self):
        """Move selected provider up in chain."""
        current_row = self.chain_list.currentRow()
        if current_row > 0:
            item = self.chain_list.takeItem(current_row)
            self.chain_list.insertItem(current_row - 1, item)
            self.chain_list.setCurrentRow(current_row - 1)

    def _move_down(self):
        """Move selected provider down in chain."""
        current_row = self.chain_list.currentRow()
        if current_row < self.chain_list.count() - 1:
            item = self.chain_list.takeItem(current_row)
            self.chain_list.insertItem(current_row + 1, item)
            self.chain_list.setCurrentRow(current_row + 1)

    def _load_settings(self):
        """Load settings from QSettings."""
        for provider_id, widgets in self.provider_widgets.items():
            # Load enabled status
            enabled_key = f"mt/providers/{provider_id}/enabled"
            default_enabled = self.PROVIDERS[provider_id]["default_enabled"]
            enabled = self.settings.value(enabled_key, default_enabled, type=bool)
            widgets["enabled"].setChecked(enabled)

            # Load rate limit
            rate_limit_key = f"mt/providers/{provider_id}/rate_limit"
            default_rate_limit = self.PROVIDERS[provider_id]["default_rate_limit"]
            rate_limit = self.settings.value(rate_limit_key, default_rate_limit, type=int)
            widgets["rate_limit"].setValue(rate_limit)

        # Load chain order
        chain_key = "mt/providers/chain"
        chain = self.settings.value(chain_key, [], type=list)
        if chain:
            # Reorder list based on saved chain
            for i, provider_id in enumerate(chain):
                for row in range(self.chain_list.count()):
                    item = self.chain_list.item(row)
                    if item.data(Qt.ItemDataRole.UserRole) == provider_id:
                        self.chain_list.insertItem(i, self.chain_list.takeItem(row))
                        break

    def _save_settings(self):
        """Save settings to QSettings."""
        for provider_id, widgets in self.provider_widgets.items():
            # Save enabled status
            enabled_key = f"mt/providers/{provider_id}/enabled"
            enabled = widgets["enabled"].isChecked()
            self.settings.setValue(enabled_key, enabled)

            # Save rate limit
            rate_limit_key = f"mt/providers/{provider_id}/rate_limit"
            rate_limit = widgets["rate_limit"].value()
            self.settings.setValue(rate_limit_key, rate_limit)

        # Save chain order
        chain = []
        for row in range(self.chain_list.count()):
            item = self.chain_list.item(row)
            provider_id = item.data(Qt.ItemDataRole.UserRole)
            chain.append(provider_id)

        chain_key = "mt/providers/chain"
        self.settings.setValue(chain_key, chain)

        self.settings.sync()

    def _restore_defaults(self):
        """Restore default settings."""
        reply = QMessageBox.question(
            self,
            "Restore Defaults",
            "Are you sure you want to restore default provider settings?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            # Restore rate limits and enabled status
            for provider_id, widgets in self.provider_widgets.items():
                default_enabled = self.PROVIDERS[provider_id]["default_enabled"]
                default_rate_limit = self.PROVIDERS[provider_id]["default_rate_limit"]

                widgets["enabled"].setChecked(default_enabled)
                widgets["rate_limit"].setValue(default_rate_limit)

            # Restore chain order
            self.chain_list.clear()
            for provider_id, provider_info in self.PROVIDERS.items():
                item = QListWidgetItem(provider_info["name"])
                item.setData(Qt.ItemDataRole.UserRole, provider_id)
                self.chain_list.addItem(item)

    def accept(self):
        """Save settings and close dialog."""
        self._save_settings()
        super().accept()


def show_provider_settings(parent=None):
    """Show provider settings dialog.

    Args:
        parent: Parent widget

    Returns:
        True if settings were changed, False if cancelled
    """
    dialog = ProviderSettingsDialog(parent)
    return dialog.exec() == QDialog.DialogCode.Accepted
