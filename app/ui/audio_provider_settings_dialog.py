"""Audio Provider Settings dialog with MT-style advanced controls."""

from __future__ import annotations

import json
import logging
from typing import Dict

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QDoubleSpinBox,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.infra.audio.audio_provider_config import (
    AudioProviderAuthMode,
    AudioProviderConfig,
    get_api_key_credential_id,
    get_service_account_credential_id,
)
from app.infra.audio.audio_provider_config_manager import AudioProviderConfigManager
from app.infra.settings import SettingsService
from app.services.audio_usage_tracker import AudioUsageTracker
from app.ui.dialogs.mms_license_gate_dialog import MMS_LICENSE_ACCEPTED_KEY, ensure_mms_license_accepted

logger = logging.getLogger(__name__)


class AudioProviderSettingsDialog(QDialog):
    """Premium audio provider settings (rate limits, chain, advanced auth/budgets)."""

    PROVIDERS = {
        "google_cloud_tts": {
            "name": "Google Cloud TTS",
            "default_rate_limit": 60,
            "default_enabled": False,
            "supports_advanced": True,
        },
        "azure_speech_tts": {
            "name": "Azure Speech TTS",
            "default_rate_limit": 60,
            "default_enabled": False,
            "supports_advanced": True,
        },
        "mms_tts_local": {
            "name": "Meta MMS-TTS Hebrew (Local)",
            "default_rate_limit": 600,
            "default_enabled": False,
            "supports_advanced": True,
        },
        "mock_local_audio": {
            "name": "Mock Local Audio",
            "default_rate_limit": 600,
            "default_enabled": True,
            "supports_advanced": False,
        },
        "mock_online_audio": {
            "name": "Mock Online Audio",
            "default_rate_limit": 120,
            "default_enabled": True,
            "supports_advanced": False,
        },
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Audio Provider Settings")
        self.setMinimumWidth(760)
        self.setMinimumHeight(640)

        self.settings = SettingsService.get_instance()
        self.config_manager = AudioProviderConfigManager(settings=self.settings)
        self.provider_widgets: Dict[str, Dict[str, object]] = {}
        self.advanced_pages: Dict[str, QWidget] = {}

        self._init_ui()
        self._load_settings()

    def _init_ui(self):
        root = QVBoxLayout(self)

        title = QLabel("<h2>Audio Provider Settings</h2>")
        root.addWidget(title)

        info = QLabel(
            "Configure audio providers, fallback chain, secure credentials, budget guards, and usage tracking."
        )
        info.setWordWrap(True)
        root.addWidget(info)

        master_group = QGroupBox("Master Settings")
        master_layout = QHBoxLayout(master_group)
        self.master_enable_checkbox = QCheckBox("Enable audio providers (master switch)")
        self.master_enable_checkbox.setChecked(True)
        self.master_enable_checkbox.toggled.connect(self._on_master_toggle)
        master_layout.addWidget(self.master_enable_checkbox)
        root.addWidget(master_group)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._create_rate_limits_tab(), "Rate Limits")
        self.tabs.addTab(self._create_chain_tab(), "Provider Chain")
        self.tabs.addTab(self._create_advanced_tab(), "Advanced Settings")
        self.tabs.addTab(self._create_playback_tab(), "Playback")
        root.addWidget(self.tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(self._restore_defaults)
        root.addWidget(buttons)

    def _create_rate_limits_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        info = QLabel(
            "Configure provider enablement and request rate limits (requests per minute)."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        for provider_id, meta in self.PROVIDERS.items():
            group = QGroupBox(meta["name"])
            form = QFormLayout(group)

            enabled_cb = QCheckBox("Enabled")
            rate_spin = QSpinBox()
            rate_spin.setMinimum(1)
            rate_spin.setMaximum(10000)
            rate_spin.setValue(int(meta["default_rate_limit"]))
            rate_spin.setSuffix(" req/min")

            form.addRow("Status:", enabled_cb)
            form.addRow("Rate limit:", rate_spin)

            self.provider_widgets[provider_id] = {
                "enabled": enabled_cb,
                "rate_limit": rate_spin,
            }
            layout.addWidget(group)

        layout.addStretch()
        return widget

    def _create_chain_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        info = QLabel(
            "Configure fallback chain order. Providers are tried top-to-bottom; disabled providers are skipped."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.chain_list = QListWidget()
        self.chain_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        layout.addWidget(self.chain_list)

        for provider_id, meta in self.PROVIDERS.items():
            item = QListWidgetItem(meta["name"])
            item.setData(Qt.ItemDataRole.UserRole, provider_id)
            self.chain_list.addItem(item)

        buttons = QHBoxLayout()
        up_btn = QPushButton("Move Up")
        up_btn.clicked.connect(self._move_up)
        down_btn = QPushButton("Move Down")
        down_btn.clicked.connect(self._move_down)
        buttons.addWidget(up_btn)
        buttons.addWidget(down_btn)
        buttons.addStretch()
        layout.addLayout(buttons)

        return widget

    def _create_advanced_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        info = QLabel(
            "<b>Advanced Settings</b><br>"
            "Authentication, budget guards, retry policy, and current usage."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        selector = QHBoxLayout()
        selector.addWidget(QLabel("Provider:"))
        self.advanced_provider_combo = QComboBox()
        for provider_id, meta in self.PROVIDERS.items():
            if meta.get("supports_advanced"):
                self.advanced_provider_combo.addItem(meta["name"], userData=provider_id)
        self.advanced_provider_combo.currentIndexChanged.connect(self._on_advanced_provider_changed)
        selector.addWidget(self.advanced_provider_combo)
        selector.addStretch()
        layout.addLayout(selector)

        self.advanced_stack = QStackedWidget()
        self.google_page = self._create_google_advanced_page()
        self.azure_page = self._create_azure_advanced_page()
        self.mms_page = self._create_mms_advanced_page()
        self.advanced_pages = {
            "google_cloud_tts": self.google_page,
            "azure_speech_tts": self.azure_page,
            "mms_tts_local": self.mms_page,
        }
        self.advanced_stack.addWidget(self.google_page)
        self.advanced_stack.addWidget(self.azure_page)
        self.advanced_stack.addWidget(self.mms_page)
        layout.addWidget(self.advanced_stack)

        pronunciation_row = QHBoxLayout()
        pronunciation_hint = QLabel("Need offline pronunciation baseline quality controls?")
        pronunciation_row.addWidget(pronunciation_hint)
        open_pron_btn = QPushButton("Open Pronunciation Bootstrap...")
        open_pron_btn.clicked.connect(self._open_pronunciation_bootstrap)
        pronunciation_row.addWidget(open_pron_btn)
        pronunciation_row.addStretch()
        layout.addLayout(pronunciation_row)

        return widget

    def _create_playback_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        info = QLabel(
            "Configure built-in playback cadence and queue behavior.\n"
            "These settings affect Play Audio actions in all main tables."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        cadence_group = QGroupBox("Cadence (ms)")
        cadence_form = QFormLayout(cadence_group)

        self.playback_pre_roll_spin = QSpinBox()
        self.playback_pre_roll_spin.setRange(0, 10000)
        self.playback_pre_roll_spin.setSuffix(" ms")
        cadence_form.addRow("Pre-roll:", self.playback_pre_roll_spin)

        self.playback_gap_spin = QSpinBox()
        self.playback_gap_spin.setRange(0, 10000)
        self.playback_gap_spin.setSuffix(" ms")
        cadence_form.addRow("Gap between items:", self.playback_gap_spin)

        self.playback_post_roll_spin = QSpinBox()
        self.playback_post_roll_spin.setRange(0, 10000)
        self.playback_post_roll_spin.setSuffix(" ms")
        cadence_form.addRow("Post-roll:", self.playback_post_roll_spin)

        layout.addWidget(cadence_group)

        mode_group = QGroupBox("Play Mode")
        mode_form = QFormLayout(mode_group)
        self.playback_mode_combo = QComboBox()
        self.playback_mode_combo.addItem("Interrupt current playback", userData="interrupt")
        self.playback_mode_combo.addItem("Enqueue new items", userData="enqueue")
        mode_form.addRow("Behavior:", self.playback_mode_combo)
        layout.addWidget(mode_group)

        preset_group = QGroupBox("Cadence Presets")
        preset_layout = QHBoxLayout(preset_group)
        preset_layout.addWidget(QLabel("Preset:"))
        self.playback_preset_combo = QComboBox()
        self.playback_preset_combo.addItems(["Normal", "Study", "Fast"])
        preset_layout.addWidget(self.playback_preset_combo)
        apply_preset_btn = QPushButton("Apply")
        apply_preset_btn.clicked.connect(self._apply_playback_preset)
        preset_layout.addWidget(apply_preset_btn)
        reset_btn = QPushButton("Reset Defaults")
        reset_btn.clicked.connect(self._reset_playback_defaults)
        preset_layout.addWidget(reset_btn)
        preset_layout.addStretch()
        layout.addWidget(preset_group)

        layout.addStretch()
        return widget

    def _create_google_advanced_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        auth_group = QGroupBox("Authentication")
        auth_layout = QVBoxLayout(auth_group)
        auth_layout.addWidget(
            QLabel("Google Cloud TTS uses Service Account JSON credentials.")
        )

        row = QHBoxLayout()
        self.google_sa_load_btn = QPushButton("Load from File...")
        self.google_sa_load_btn.clicked.connect(self._load_google_sa_json)
        row.addWidget(self.google_sa_load_btn)

        self.google_sa_clear_btn = QPushButton("Clear")
        self.google_sa_clear_btn.clicked.connect(self._clear_google_sa_json)
        row.addWidget(self.google_sa_clear_btn)
        row.addStretch()
        auth_layout.addLayout(row)

        self.google_sa_preview = QLabel("No Service Account JSON configured")
        self.google_sa_preview.setStyleSheet("color: gray; font-style: italic;")
        self.google_sa_preview.setWordWrap(True)
        auth_layout.addWidget(self.google_sa_preview)
        layout.addWidget(auth_group)

        voice_group = QGroupBox("Voice / Speech")
        voice_form = QFormLayout(voice_group)
        self.google_voice_combo = QComboBox()
        self.google_voice_combo.setEditable(True)
        self.google_voice_combo.setMaxVisibleItems(50)
        voice_form.addRow("Voice ID:", self.google_voice_combo)
        self.google_refresh_voices_btn = QPushButton("Refresh voices")
        self.google_refresh_voices_btn.clicked.connect(self._refresh_google_voices)
        voice_form.addRow("", self.google_refresh_voices_btn)
        self.google_speech_rate = QDoubleSpinBox()
        self.google_speech_rate.setRange(0.5, 2.0)
        self.google_speech_rate.setSingleStep(0.05)
        self.google_speech_rate.setDecimals(2)
        self.google_speech_rate.setSuffix(" x")
        voice_form.addRow("Speech rate:", self.google_speech_rate)
        layout.addWidget(voice_group)

        (
            self.google_max_chars_per_request,
            self.google_max_chars_per_day,
            self.google_max_chars_per_month,
            self.google_max_requests_per_minute,
            self.google_max_requests_per_day,
            self.google_fail_closed,
        ) = self._create_budget_group(layout)

        (
            self.google_timeout_seconds,
            self.google_max_retries,
            self.google_backoff_ms,
        ) = self._create_retry_group(layout)

        self.google_usage_label = self._create_usage_group(layout, "google_cloud_tts")
        self._create_diagnostics_group(layout, "google_cloud_tts")

        layout.addStretch()
        return page

    def _create_azure_advanced_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        auth_group = QGroupBox("Authentication")
        auth_layout = QVBoxLayout(auth_group)
        auth_layout.addWidget(QLabel("Azure Speech TTS requires API key + region."))

        row = QHBoxLayout()
        self.azure_api_set_btn = QPushButton("Set API Key...")
        self.azure_api_set_btn.clicked.connect(self._set_azure_api_key)
        row.addWidget(self.azure_api_set_btn)

        self.azure_api_clear_btn = QPushButton("Clear")
        self.azure_api_clear_btn.clicked.connect(self._clear_azure_api_key)
        row.addWidget(self.azure_api_clear_btn)

        row.addWidget(QLabel("Region:"))
        self.azure_region_combo = QComboBox()
        self.azure_region_combo.setEditable(True)
        self.azure_region_combo.addItems(["eastus", "westeurope", "uksouth", "southeastasia"])
        row.addWidget(self.azure_region_combo)
        row.addStretch()
        auth_layout.addLayout(row)

        self.azure_api_preview = QLabel("No API key configured")
        self.azure_api_preview.setStyleSheet("color: gray; font-style: italic;")
        self.azure_api_preview.setWordWrap(True)
        auth_layout.addWidget(self.azure_api_preview)
        layout.addWidget(auth_group)

        voice_group = QGroupBox("Voice / Speech")
        voice_form = QFormLayout(voice_group)
        self.azure_voice_combo = QComboBox()
        self.azure_voice_combo.setEditable(True)
        voice_form.addRow("Voice ID:", self.azure_voice_combo)
        self.azure_refresh_voices_btn = QPushButton("Refresh voices")
        self.azure_refresh_voices_btn.clicked.connect(self._refresh_azure_voices)
        voice_form.addRow("", self.azure_refresh_voices_btn)
        self.azure_speech_rate = QDoubleSpinBox()
        self.azure_speech_rate.setRange(0.5, 2.0)
        self.azure_speech_rate.setSingleStep(0.05)
        self.azure_speech_rate.setDecimals(2)
        self.azure_speech_rate.setSuffix(" x")
        voice_form.addRow("Speech rate:", self.azure_speech_rate)
        layout.addWidget(voice_group)

        (
            self.azure_max_chars_per_request,
            self.azure_max_chars_per_day,
            self.azure_max_chars_per_month,
            self.azure_max_requests_per_minute,
            self.azure_max_requests_per_day,
            self.azure_fail_closed,
        ) = self._create_budget_group(layout)

        (
            self.azure_timeout_seconds,
            self.azure_max_retries,
            self.azure_backoff_ms,
        ) = self._create_retry_group(layout)

        self.azure_usage_label = self._create_usage_group(layout, "azure_speech_tts")
        self._create_diagnostics_group(layout, "azure_speech_tts")

        layout.addStretch()
        return page

    def _create_mms_advanced_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        local_group = QGroupBox("Local MMS Provider")
        form = QFormLayout(local_group)

        self.mms_license_state = QLabel("")
        self.mms_license_state.setWordWrap(True)
        form.addRow("License gate:", self.mms_license_state)

        self.mms_accept_btn = QPushButton("Review / Accept License")
        self.mms_accept_btn.clicked.connect(self._accept_mms_license)
        form.addRow("", self.mms_accept_btn)

        path_row = QHBoxLayout()
        self.mms_model_path_btn = QPushButton("Select model folder...")
        self.mms_model_path_btn.clicked.connect(self._browse_mms_model_path)
        path_row.addWidget(self.mms_model_path_btn)
        path_row.addStretch()
        form.addRow("Model path:", path_row)

        self.mms_model_path_label = QLabel("(not configured)")
        self.mms_model_path_label.setWordWrap(True)
        form.addRow("", self.mms_model_path_label)

        layout.addWidget(local_group)

        info = QLabel(
            "mms_tts_local is optional and disabled by default. "
            "Model weights are external and not bundled into base installer."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        voice_group = QGroupBox("Voice / Speech")
        voice_form = QFormLayout(voice_group)
        self.mms_voice_edit = QLineEdit()
        self.mms_voice_edit.setPlaceholderText("mms-he")
        voice_form.addRow("Voice ID:", self.mms_voice_edit)
        self.mms_speech_rate = QDoubleSpinBox()
        self.mms_speech_rate.setRange(0.5, 2.0)
        self.mms_speech_rate.setSingleStep(0.05)
        self.mms_speech_rate.setDecimals(2)
        self.mms_speech_rate.setSuffix(" x")
        voice_form.addRow("Speech rate:", self.mms_speech_rate)
        layout.addWidget(voice_group)

        self.mms_usage_label = self._create_usage_group(layout, "mms_tts_local")
        self._create_diagnostics_group(layout, "mms_tts_local")
        layout.addStretch()
        return page

    def _create_budget_group(self, root_layout: QVBoxLayout):
        group = QGroupBox("Budget Guards (Fail-Closed)")
        form = QFormLayout(group)

        max_chars_per_request = QSpinBox()
        max_chars_per_request.setRange(100, 100000)
        max_chars_per_request.setSuffix(" chars")
        form.addRow("Max chars per request:", max_chars_per_request)

        max_chars_per_day = QSpinBox()
        max_chars_per_day.setRange(0, 20000000)
        max_chars_per_day.setSpecialValueText("Unlimited")
        max_chars_per_day.setSuffix(" chars")
        form.addRow("Max chars per day:", max_chars_per_day)

        max_chars_per_month = QSpinBox()
        max_chars_per_month.setRange(0, 500000000)
        max_chars_per_month.setSpecialValueText("Unlimited")
        max_chars_per_month.setSuffix(" chars")
        form.addRow("Max chars per month:", max_chars_per_month)

        max_requests_per_minute = QSpinBox()
        max_requests_per_minute.setRange(1, 5000)
        max_requests_per_minute.setSuffix(" req/min")
        form.addRow("Max requests per minute:", max_requests_per_minute)

        max_requests_per_day = QSpinBox()
        max_requests_per_day.setRange(0, 1000000)
        max_requests_per_day.setSpecialValueText("Unlimited")
        max_requests_per_day.setSuffix(" req")
        form.addRow("Max requests per day:", max_requests_per_day)

        fail_closed = QCheckBox("Fail-closed when budget limit is exceeded")
        fail_closed.setChecked(True)
        form.addRow("Policy:", fail_closed)

        root_layout.addWidget(group)
        return (
            max_chars_per_request,
            max_chars_per_day,
            max_chars_per_month,
            max_requests_per_minute,
            max_requests_per_day,
            fail_closed,
        )

    def _create_retry_group(self, root_layout: QVBoxLayout):
        group = QGroupBox("Retry / Timeout")
        form = QFormLayout(group)

        timeout_seconds = QSpinBox()
        timeout_seconds.setRange(3, 300)
        timeout_seconds.setSuffix(" sec")
        form.addRow("Timeout:", timeout_seconds)

        max_retries = QSpinBox()
        max_retries.setRange(1, 10)
        form.addRow("Max retries:", max_retries)

        backoff_ms = QSpinBox()
        backoff_ms.setRange(100, 60000)
        backoff_ms.setSuffix(" ms")
        form.addRow("Base backoff:", backoff_ms)

        root_layout.addWidget(group)
        return timeout_seconds, max_retries, backoff_ms

    def _create_usage_group(self, root_layout: QVBoxLayout, provider_id: str) -> QLabel:
        group = QGroupBox("Current Usage")
        layout = QVBoxLayout(group)

        label = QLabel("Loading usage statistics...")
        label.setWordWrap(True)
        layout.addWidget(label)

        refresh_btn = QPushButton("Refresh Usage")
        refresh_btn.clicked.connect(lambda _=False, pid=provider_id: self._refresh_usage(pid))
        layout.addWidget(refresh_btn)

        root_layout.addWidget(group)
        return label

    def _create_diagnostics_group(self, root_layout: QVBoxLayout, provider_id: str) -> None:
        group = QGroupBox("Diagnostics")
        layout = QHBoxLayout(group)
        test_btn = QPushButton("Test API Connection")
        test_btn.clicked.connect(lambda _=False, pid=provider_id: self._test_provider_connection(pid))
        layout.addWidget(test_btn)
        layout.addStretch()
        root_layout.addWidget(group)

    def _move_up(self):
        row = self.chain_list.currentRow()
        if row > 0:
            item = self.chain_list.takeItem(row)
            self.chain_list.insertItem(row - 1, item)
            self.chain_list.setCurrentRow(row - 1)

    def _move_down(self):
        row = self.chain_list.currentRow()
        if 0 <= row < self.chain_list.count() - 1:
            item = self.chain_list.takeItem(row)
            self.chain_list.insertItem(row + 1, item)
            self.chain_list.setCurrentRow(row + 1)

    def _on_master_toggle(self, enabled: bool):
        self.tabs.setEnabled(enabled)

    def _on_advanced_provider_changed(self, _index: int):
        provider_id = self.advanced_provider_combo.currentData()
        if not provider_id:
            return
        page = self.advanced_pages.get(provider_id)
        if page is not None:
            self.advanced_stack.setCurrentWidget(page)
        self._refresh_usage(provider_id)

    def _apply_playback_preset(self):
        preset = (self.playback_preset_combo.currentText() or "").strip().lower()
        if preset == "study":
            values = (300, 800, 450)
        elif preset == "fast":
            values = (100, 250, 120)
        else:
            values = (200, 550, 300)
        self.playback_pre_roll_spin.setValue(values[0])
        self.playback_gap_spin.setValue(values[1])
        self.playback_post_roll_spin.setValue(values[2])

    def _reset_playback_defaults(self):
        self.playback_pre_roll_spin.setValue(200)
        self.playback_gap_spin.setValue(550)
        self.playback_post_roll_spin.setValue(300)
        idx = self.playback_mode_combo.findData("interrupt")
        if idx >= 0:
            self.playback_mode_combo.setCurrentIndex(idx)

    def _load_settings(self):
        self.master_enable_checkbox.setChecked(self.settings.get_bool("audio/providers/enabled", True))

        for provider_id, widgets in self.provider_widgets.items():
            config = self.config_manager.load_config(provider_id)
            enabled_cb = widgets["enabled"]
            rate_spin = widgets["rate_limit"]
            enabled_cb.setChecked(bool(config.enabled))
            rate_spin.setValue(int(config.max_requests_per_minute))

        chain = self.settings.get_json("audio/providers/chain", [])
        if isinstance(chain, list) and chain:
            for i, provider_id in enumerate(chain):
                for row in range(self.chain_list.count()):
                    item = self.chain_list.item(row)
                    if item.data(Qt.ItemDataRole.UserRole) == provider_id:
                        self.chain_list.insertItem(i, self.chain_list.takeItem(row))
                        break

        self._load_google_advanced_settings()
        self._load_azure_advanced_settings()
        self._load_mms_advanced_settings()
        self._reset_playback_defaults()
        self._load_playback_settings()
        self._on_advanced_provider_changed(self.advanced_provider_combo.currentIndex())

    def _load_google_advanced_settings(self):
        config = self.config_manager.load_config("google_cloud_tts")
        self._load_voice_cache(self.google_voice_combo, "google_cloud_tts")
        self.google_voice_combo.setCurrentText(config.default_voice or "")
        self.google_speech_rate.setValue(float(config.speech_rate or 1.0))
        self.google_max_chars_per_request.setValue(int(config.max_chars_per_request))
        self.google_max_chars_per_day.setValue(int(config.max_chars_per_day or 0))
        self.google_max_chars_per_month.setValue(int(config.max_chars_per_month or 0))
        self.google_max_requests_per_minute.setValue(int(config.max_requests_per_minute))
        self.google_max_requests_per_day.setValue(int(config.max_requests_per_day or 0))
        self.google_fail_closed.setChecked(bool(config.fail_closed))
        self.google_timeout_seconds.setValue(int(round(config.timeout_seconds)))
        self.google_max_retries.setValue(int(config.retry_max_attempts))
        self.google_backoff_ms.setValue(int(config.retry_backoff_base_ms))

        sa_cred_id = config.service_account_credential_id or get_service_account_credential_id("google_cloud_tts")
        sa_json = self.config_manager.get_credential(sa_cred_id)
        if sa_json:
            try:
                info = json.loads(sa_json)
                project_id = info.get("project_id", "unknown")
                self.google_sa_preview.setText(f"✓ Service Account configured (project: {project_id})")
                self.google_sa_preview.setStyleSheet("color: #2e7d32;")
            except Exception:
                self.google_sa_preview.setText("Service Account credential exists (invalid JSON preview)")
                self.google_sa_preview.setStyleSheet("color: #f57c00;")
        else:
            self.google_sa_preview.setText("No Service Account JSON configured")
            self.google_sa_preview.setStyleSheet("color: gray; font-style: italic;")

    def _load_azure_advanced_settings(self):
        config = self.config_manager.load_config("azure_speech_tts")
        self._load_voice_cache(self.azure_voice_combo, "azure_speech_tts")
        self.azure_voice_combo.setCurrentText(config.default_voice or "")
        self.azure_speech_rate.setValue(float(config.speech_rate or 1.0))
        self.azure_region_combo.setCurrentText(config.region or "eastus")
        self.azure_max_chars_per_request.setValue(int(config.max_chars_per_request))
        self.azure_max_chars_per_day.setValue(int(config.max_chars_per_day or 0))
        self.azure_max_chars_per_month.setValue(int(config.max_chars_per_month or 0))
        self.azure_max_requests_per_minute.setValue(int(config.max_requests_per_minute))
        self.azure_max_requests_per_day.setValue(int(config.max_requests_per_day or 0))
        self.azure_fail_closed.setChecked(bool(config.fail_closed))
        self.azure_timeout_seconds.setValue(int(round(config.timeout_seconds)))
        self.azure_max_retries.setValue(int(config.retry_max_attempts))
        self.azure_backoff_ms.setValue(int(config.retry_backoff_base_ms))

        api_cred_id = config.api_key_credential_id or get_api_key_credential_id("azure_speech_tts")
        api_key = self.config_manager.get_credential(api_cred_id)
        if api_key:
            self.azure_api_preview.setText(f"✓ API key configured ({len(api_key)} chars)")
            self.azure_api_preview.setStyleSheet("color: #2e7d32;")
        else:
            self.azure_api_preview.setText("No API key configured")
            self.azure_api_preview.setStyleSheet("color: gray; font-style: italic;")

    def _load_mms_advanced_settings(self):
        config = self.config_manager.load_config("mms_tts_local")
        self.mms_voice_edit.setText(config.default_voice or "mms-he")
        self.mms_speech_rate.setValue(float(config.speech_rate or 1.0))
        model_path = (config.model_path or "").strip()
        self.mms_model_path_label.setText(model_path or "(not configured)")
        accepted = self.settings.get_bool(MMS_LICENSE_ACCEPTED_KEY, False)
        self.mms_license_state.setText("Accepted" if accepted else "Not accepted")
        self.mms_license_state.setStyleSheet("color: #2e7d32;" if accepted else "color: #d32f2f;")

    def _load_playback_settings(self):
        self.playback_pre_roll_spin.setValue(self.settings.get_int("audio/playback/pre_roll_ms", 200))
        self.playback_gap_spin.setValue(self.settings.get_int("audio/playback/gap_ms", 550))
        self.playback_post_roll_spin.setValue(self.settings.get_int("audio/playback/post_roll_ms", 300))
        mode = (self.settings.get_string("audio/playback/play_mode", "interrupt") or "interrupt").strip().lower()
        idx = self.playback_mode_combo.findData("enqueue" if mode == "enqueue" else "interrupt")
        self.playback_mode_combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _save_playback_settings(self):
        self.settings.set_value("audio/playback/pre_roll_ms", int(self.playback_pre_roll_spin.value()))
        self.settings.set_value("audio/playback/gap_ms", int(self.playback_gap_spin.value()))
        self.settings.set_value("audio/playback/post_roll_ms", int(self.playback_post_roll_spin.value()))
        mode = self.playback_mode_combo.currentData() or "interrupt"
        self.settings.set_value("audio/playback/play_mode", str(mode))
        try:
            from app.services.audio_player_service import AudioPlayerService

            player = AudioPlayerService.get_instance()
            player.set_cadence(
                pre_roll_ms=int(self.playback_pre_roll_spin.value()),
                gap_ms=int(self.playback_gap_spin.value()),
                post_roll_ms=int(self.playback_post_roll_spin.value()),
            )
            player.set_play_mode(str(mode))
        except Exception as e:
            logger.debug("Audio player settings apply deferred: %s", e)

    def _save_settings(self):
        self.settings.set_value("audio/providers/enabled", self.master_enable_checkbox.isChecked())

        for provider_id, widgets in self.provider_widgets.items():
            config = self.config_manager.load_config(provider_id)
            config.enabled = widgets["enabled"].isChecked()
            config.max_requests_per_minute = int(widgets["rate_limit"].value())
            self.config_manager.save_config(config)

        chain = []
        for row in range(self.chain_list.count()):
            item = self.chain_list.item(row)
            chain.append(item.data(Qt.ItemDataRole.UserRole))
        self.settings.set_json("audio/providers/chain", chain)

        self._save_google_advanced_settings()
        self._save_azure_advanced_settings()
        self._save_mms_advanced_settings()
        self._save_playback_settings()

        self.settings.sync()

    def _save_google_advanced_settings(self):
        config = self.config_manager.load_config("google_cloud_tts")
        config.auth_mode = AudioProviderAuthMode.SERVICE_ACCOUNT_JSON
        config.service_account_credential_id = get_service_account_credential_id("google_cloud_tts")
        config.default_voice = self.google_voice_combo.currentText().strip() or None
        config.speech_rate = float(self.google_speech_rate.value())
        config.max_chars_per_request = int(self.google_max_chars_per_request.value())
        config.max_chars_per_day = int(self.google_max_chars_per_day.value()) or None
        config.max_chars_per_month = int(self.google_max_chars_per_month.value()) or None
        config.max_requests_per_minute = int(self.google_max_requests_per_minute.value())
        config.max_requests_per_day = int(self.google_max_requests_per_day.value()) or None
        config.fail_closed = self.google_fail_closed.isChecked()
        config.timeout_seconds = float(self.google_timeout_seconds.value())
        config.retry_max_attempts = int(self.google_max_retries.value())
        config.retry_backoff_base_ms = int(self.google_backoff_ms.value())
        self.config_manager.save_config(config)

    def _save_azure_advanced_settings(self):
        config = self.config_manager.load_config("azure_speech_tts")
        config.auth_mode = AudioProviderAuthMode.API_KEY
        config.api_key_credential_id = get_api_key_credential_id("azure_speech_tts")
        config.region = self.azure_region_combo.currentText().strip() or "eastus"
        config.default_voice = self.azure_voice_combo.currentText().strip() or None
        config.speech_rate = float(self.azure_speech_rate.value())
        config.max_chars_per_request = int(self.azure_max_chars_per_request.value())
        config.max_chars_per_day = int(self.azure_max_chars_per_day.value()) or None
        config.max_chars_per_month = int(self.azure_max_chars_per_month.value()) or None
        config.max_requests_per_minute = int(self.azure_max_requests_per_minute.value())
        config.max_requests_per_day = int(self.azure_max_requests_per_day.value()) or None
        config.fail_closed = self.azure_fail_closed.isChecked()
        config.timeout_seconds = float(self.azure_timeout_seconds.value())
        config.retry_max_attempts = int(self.azure_max_retries.value())
        config.retry_backoff_base_ms = int(self.azure_backoff_ms.value())
        self.config_manager.save_config(config)

    def _save_mms_advanced_settings(self):
        config = self.config_manager.load_config("mms_tts_local")
        config.auth_mode = AudioProviderAuthMode.NONE
        config.default_voice = self.mms_voice_edit.text().strip() or "mms-he"
        config.speech_rate = float(self.mms_speech_rate.value())
        model_path = self.mms_model_path_label.text().strip()
        config.model_path = None if model_path in {"", "(not configured)"} else model_path
        self.config_manager.save_config(config)

    def _load_google_sa_json(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Service Account JSON",
            "",
            "JSON Files (*.json);;All Files (*)",
        )
        if not file_path:
            return

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                payload = f.read()
            data = json.loads(payload)
            if "project_id" not in data:
                QMessageBox.warning(self, "Invalid JSON", "Service Account JSON must include project_id.")
                return

            cred_id = get_service_account_credential_id("google_cloud_tts")
            self.config_manager.set_credential(cred_id, payload)
            self.google_sa_preview.setText(f"✓ Service Account configured (project: {data.get('project_id')})")
            self.google_sa_preview.setStyleSheet("color: #2e7d32;")
            QMessageBox.information(self, "Success", "Service Account JSON loaded.")
        except json.JSONDecodeError as e:
            QMessageBox.warning(self, "Invalid JSON", f"Failed to parse JSON: {e}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load Service Account JSON: {e}")

    def _clear_google_sa_json(self):
        reply = QMessageBox.question(
            self,
            "Clear Credentials",
            "Clear Google Cloud TTS Service Account credentials?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        cred_id = get_service_account_credential_id("google_cloud_tts")
        self.config_manager.delete_credential(cred_id)
        self.google_sa_preview.setText("No Service Account JSON configured")
        self.google_sa_preview.setStyleSheet("color: gray; font-style: italic;")

    def _set_azure_api_key(self):
        value, ok = QInputDialog.getText(
            self,
            "Azure API Key",
            "Enter Azure Speech API key:",
            echo=QLineEdit.EchoMode.Password,
        )
        if not ok:
            return
        api_key = (value or "").strip()
        if not api_key:
            return

        cred_id = get_api_key_credential_id("azure_speech_tts")
        self.config_manager.set_credential(cred_id, api_key)
        self.azure_api_preview.setText(f"✓ API key configured ({len(api_key)} chars)")
        self.azure_api_preview.setStyleSheet("color: #2e7d32;")

    def _clear_azure_api_key(self):
        reply = QMessageBox.question(
            self,
            "Clear Credentials",
            "Clear Azure Speech API key?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        cred_id = get_api_key_credential_id("azure_speech_tts")
        self.config_manager.delete_credential(cred_id)
        self.azure_api_preview.setText("No API key configured")
        self.azure_api_preview.setStyleSheet("color: gray; font-style: italic;")

    def _accept_mms_license(self):
        if ensure_mms_license_accepted(parent=self):
            self._load_mms_advanced_settings()
            QMessageBox.information(self, "License Gate", "License accepted.")

    def _browse_mms_model_path(self):
        selected = QFileDialog.getExistingDirectory(self, "Select MMS model directory")
        if selected:
            self.mms_model_path_label.setText(selected)

    def _voice_cache_key(self, provider_id: str) -> str:
        return f"audio/providers/{provider_id}/voices_cache"

    def _load_voice_cache(self, combo: QComboBox, provider_id: str) -> None:
        combo.clear()
        cached = self.settings.get_json(self._voice_cache_key(provider_id), [])
        if isinstance(cached, list):
            unique = []
            seen = set()
            for raw in cached:
                value = str(raw or "").strip()
                if not value or value in seen:
                    continue
                seen.add(value)
                unique.append(value)
            combo.addItems(unique)

    def _save_voice_cache(self, provider_id: str, voices: list[str]) -> None:
        normalized: list[str] = []
        seen = set()
        for raw in voices:
            value = str(raw or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            normalized.append(value)
        self.settings.set_json(self._voice_cache_key(provider_id), normalized[:200])

    def _refresh_google_voices(self):
        try:
            from app.infra.audio.providers.google_cloud_tts_provider import GoogleCloudTTSProvider

            self._save_google_advanced_settings()
            provider = GoogleCloudTTSProvider(config_manager=self.config_manager)
            voices, error = provider.list_voices(language_code="he-IL")
            if error:
                QMessageBox.warning(self, "Voice Refresh Failed", error)
                return
            self._save_voice_cache("google_cloud_tts", voices)
            current = self.google_voice_combo.currentText().strip()
            self._load_voice_cache(self.google_voice_combo, "google_cloud_tts")
            if current:
                self.google_voice_combo.setCurrentText(current)
            QMessageBox.information(self, "Voices Refreshed", f"Loaded {len(voices)} voices.")
        except Exception as e:
            QMessageBox.warning(self, "Voice Refresh Failed", str(e))

    def _refresh_azure_voices(self):
        try:
            from app.infra.audio.providers.azure_speech_tts_provider import AzureSpeechTTSProvider

            self._save_azure_advanced_settings()
            provider = AzureSpeechTTSProvider(config_manager=self.config_manager)
            voices, error = provider.list_voices(language_code="he-IL")
            if error:
                QMessageBox.warning(self, "Voice Refresh Failed", error)
                return
            self._save_voice_cache("azure_speech_tts", voices)
            current = self.azure_voice_combo.currentText().strip()
            self._load_voice_cache(self.azure_voice_combo, "azure_speech_tts")
            if current:
                self.azure_voice_combo.setCurrentText(current)
            QMessageBox.information(self, "Voices Refreshed", f"Loaded {len(voices)} voices.")
        except Exception as e:
            QMessageBox.warning(self, "Voice Refresh Failed", str(e))

    def _test_provider_connection(self, provider_id: str):
        provider_title = self.PROVIDERS.get(provider_id, {}).get("name", provider_id)
        try:
            if provider_id == "google_cloud_tts":
                self._save_google_advanced_settings()
            elif provider_id == "azure_speech_tts":
                self._save_azure_advanced_settings()
            elif provider_id == "mms_tts_local":
                self._save_mms_advanced_settings()
            self.settings.sync()
        except Exception as e:
            QMessageBox.warning(
                self,
                "Settings Error",
                f"Failed to apply {provider_title} settings before test:\n{e}",
            )
            return

        try:
            from app.domain.normalization.normalizer import normalize_for_tm
            from app.infra.audio import AudioGenerationRequest
            from app.infra.audio.local_providers_setup import register_default_audio_providers
            from app.infra.audio.providers_registry import AudioProvidersRegistry

            register_default_audio_providers()
            provider = AudioProvidersRegistry().get(provider_id)
            if not provider:
                QMessageBox.warning(
                    self,
                    "Provider Not Found",
                    f"{provider_title} is not registered. Restart the app and retry.",
                )
                return

            source_text = "שלום"
            source_norm = normalize_for_tm("he", source_text, "surface").norm or source_text
            provider_cfg = self.config_manager.load_config(provider_id)
            request = AudioGenerationRequest(
                source_text=source_text,
                source_lang="he",
                source_norm=source_norm,
                voice_id=provider_cfg.default_voice or "default",
                speed=float(provider_cfg.speech_rate or 1.0),
                trace_id=f"ui-test-{provider_id}",
            )

            progress = QProgressDialog(
                f"Testing {provider_title}...\nGenerating sample audio for '{source_text}'",
                None,
                0,
                0,
                self,
            )
            progress.setWindowTitle("Test API Connection")
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.setMinimumDuration(0)
            progress.setCancelButton(None)
            progress.show()

            result = provider.generate(request)
            progress.close()

            if result.is_success:
                QMessageBox.information(
                    self,
                    "Connection Successful",
                    f"✓ {provider_title} is working.\n\n"
                    f"Sample: '{source_text}' (he)\n"
                    f"Bytes: {len(result.audio_bytes or b'')}\n"
                    f"MIME: {result.mime_type}",
                )
                return

            details = str(result.error_message or "Unknown error")
            if result.error_kind is not None:
                details = f"{result.error_kind.value}: {details}"
            QMessageBox.critical(
                self,
                "Connection Failed",
                f"✗ {provider_title} test failed.\n\n{details}",
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Test Error",
                f"Failed to test {provider_title} connection:\n{e}",
            )

    def _refresh_usage(self, provider_id: str):
        label_map = {
            "google_cloud_tts": self.google_usage_label,
            "azure_speech_tts": self.azure_usage_label,
            "mms_tts_local": self.mms_usage_label,
        }
        label = label_map.get(provider_id)
        if not label:
            return

        try:
            from app.services.db_service import DBService

            with DBService.get_instance().get_session() as session:
                summary = AudioUsageTracker(session).get_usage_summary(provider_id)

            label.setText(
                "<b>Current Usage:</b><br>"
                f"• This minute: {summary['minute']['request_count']} requests, {summary['minute']['char_count']} chars<br>"
                f"• Today: {summary['day']['request_count']} requests, {summary['day']['char_count']} chars<br>"
                f"• This month: {summary['month']['request_count']} requests, {summary['month']['char_count']} chars"
            )
        except Exception as e:
            label.setText(f"Error loading usage: {e}")

    def _restore_defaults(self):
        reply = QMessageBox.question(
            self,
            "Restore Defaults",
            "Restore default audio provider settings?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.master_enable_checkbox.setChecked(True)

        for provider_id, widgets in self.provider_widgets.items():
            meta = self.PROVIDERS[provider_id]
            widgets["enabled"].setChecked(bool(meta["default_enabled"]))
            widgets["rate_limit"].setValue(int(meta["default_rate_limit"]))

        self.chain_list.clear()
        for provider_id, meta in self.PROVIDERS.items():
            item = QListWidgetItem(meta["name"])
            item.setData(Qt.ItemDataRole.UserRole, provider_id)
            self.chain_list.addItem(item)

        self._load_google_advanced_settings()
        self._load_azure_advanced_settings()
        self._load_mms_advanced_settings()

    def _open_pronunciation_bootstrap(self):
        from app.ui.dialogs.pronunciation_bootstrap_dialog import show_pronunciation_bootstrap_dialog

        show_pronunciation_bootstrap_dialog(parent=self)

    def accept(self):
        self._save_settings()
        super().accept()


def show_audio_provider_settings(*, parent=None) -> bool:
    """Show audio provider settings dialog and return True if saved."""
    dialog = AudioProviderSettingsDialog(parent=parent)
    return dialog.exec() == QDialog.DialogCode.Accepted
