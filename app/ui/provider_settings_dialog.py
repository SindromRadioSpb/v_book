"""Provider Settings Dialog for MT rate limit configuration.

Allows users to configure:
- Rate limits per provider (requests per minute)
- Enable/disable providers
- Provider priority in chain
- Advanced settings (auth, budget guards, retry policy) - PATCH-06
- Usage tracking display - PATCH-06
"""

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.infra.security import CredentialStore
from app.infra.settings import SettingsService
from app.infra.translators.provider_config import (
    ProviderAuthConfig,
    ProviderAuthMode,
    ProviderLimitsConfig,
    ProviderRetryPolicy,
)
from app.infra.translators.provider_config_manager import ProviderConfigManager
from app.services.db_service import DBService
from app.services.mt_usage_tracker import MTUsageTracker


class ProviderSettingsDialog(QDialog):
    """Dialog for configuring MT provider settings."""

    # Provider registry with defaults
    PROVIDERS = {
        "google_translate": {
            "name": "Google Translate (Free)",
            "default_rate_limit": 60,  # Rate-limited by Google
            "default_enabled": True,  # Always available
            "supports_advanced": False,  # No auth required
        },
        "google_cloud_translate": {
            "name": "Google Cloud Translate (Official v3)",
            "default_rate_limit": 60,
            "default_enabled": False,  # Disabled until auth configured
            "supports_advanced": True,  # Requires Service Account JSON
        },
        "deepl": {
            "name": "DeepL",
            "default_rate_limit": 60,
            "default_enabled": True,
            "supports_advanced": False,
        },
        "microsoft": {
            "name": "Microsoft Translator",
            "default_rate_limit": 60,
            "default_enabled": True,
            "supports_advanced": False,
        },
        "libretranslate": {
            "name": "LibreTranslate",
            "default_rate_limit": 60,
            "default_enabled": True,
            "supports_advanced": False,
        },
        "local_nllb": {
            "name": "Local NLLB (Offline)",
            "default_rate_limit": 9999,  # Unlimited for local
            "default_enabled": False,  # Disabled by default until model installed
            "supports_advanced": False,
        },
        "local_seamless": {
            "name": "Local Seamless M4T (Offline)",
            "default_rate_limit": 9999,  # Unlimited for local
            "default_enabled": False,  # Disabled by default until model installed
            "supports_advanced": False,
        },
        "local_hymt": {
            "name": "Local HY-MT 1.5 (Offline)",
            "default_rate_limit": 9999,  # Unlimited for local
            "default_enabled": False,  # Disabled by default until model installed
            "supports_advanced": False,
        },
        "local_hymt_7b_gptq": {
            "name": "Local HY-MT 1.5 7B GPTQ (Offline, Experimental)",
            "default_rate_limit": 9999,  # Unlimited for local
            "default_enabled": False,  # Requires auto-gptq + manual model install
            "supports_advanced": False,
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
        self.setMinimumWidth(700)
        self.setMinimumHeight(600)

        self.settings = settings if settings is not None else QSettings()

        # Initialize config manager for advanced settings
        settings_service = SettingsService.get_instance()
        self.config_manager = ProviderConfigManager(settings_service)

        # Store widgets for each provider
        self.provider_widgets = {}
        self.advanced_widgets = {}  # For advanced config widgets

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

        # Master enable checkbox
        master_group = QGroupBox("Master Settings")
        master_layout = QHBoxLayout(master_group)

        self.master_enable_checkbox = QCheckBox("Enable MT Providers (master switch)")
        self.master_enable_checkbox.setToolTip(
            "Master switch to enable or disable all MT providers. "
            "When disabled, no machine translation will be performed."
        )
        self.master_enable_checkbox.setChecked(True)  # Default enabled
        self.master_enable_checkbox.toggled.connect(self._on_master_toggle)
        master_layout.addWidget(self.master_enable_checkbox)

        layout.addWidget(master_group)

        # Tabs
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # Tab 1: Rate Limits
        rate_limits_tab = self._create_rate_limits_tab()
        self.tabs.addTab(rate_limits_tab, "Rate Limits")

        # Tab 2: Provider Chain
        chain_tab = self._create_chain_tab()
        self.tabs.addTab(chain_tab, "Provider Chain")

        # Tab 3: Advanced Settings (for providers that support it)
        advanced_tab = self._create_advanced_settings_tab()
        self.tabs.addTab(advanced_tab, "Advanced Settings")

        # Tab 4: Prompt Policy — Basic Mode (PPS PATCH-09)
        pps_tab = self._create_prompt_policy_tab()
        self.tabs.addTab(pps_tab, "Prompt Policy")

        # Tab 5: Prompt Audit — PPS PATCH-05 debug panel
        audit_tab = self._create_prompt_audit_tab()
        self.tabs.addTab(audit_tab, "Prompt Audit")

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
            rate_limit_spin.setToolTip(f"Maximum requests per minute for {provider_info['name']}")

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

    def _on_master_toggle(self, enabled: bool):
        """Handle master enable checkbox toggle.

        Args:
            enabled: True if MT providers are enabled, False otherwise
        """
        # Enable/disable all tabs when master switch is toggled
        self.tabs.setEnabled(enabled)

    def _create_advanced_settings_tab(self) -> QWidget:
        """Create advanced settings tab (auth, budget guards, usage tracking)."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Info
        info = QLabel(
            "<b>Advanced Settings</b><br>"
            "Configure authentication, budget guards, and retry policies for official API providers."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        # Provider selector
        selector_layout = QHBoxLayout()
        selector_layout.addWidget(QLabel("Provider:"))

        self.advanced_provider_combo = QComboBox()
        for provider_id, provider_info in self.PROVIDERS.items():
            if provider_info.get("supports_advanced", False):
                self.advanced_provider_combo.addItem(provider_info["name"], userData=provider_id)
        self.advanced_provider_combo.currentIndexChanged.connect(self._on_advanced_provider_changed)
        selector_layout.addWidget(self.advanced_provider_combo)
        selector_layout.addStretch()
        layout.addLayout(selector_layout)

        # Stack widget for provider-specific settings
        self.advanced_stack = QWidget()
        self.advanced_stack_layout = QVBoxLayout(self.advanced_stack)

        # Google Cloud Translate settings (only advanced provider for now)
        self.gcp_settings = self._create_gcp_settings()
        self.advanced_stack_layout.addWidget(self.gcp_settings)

        layout.addWidget(self.advanced_stack)

        layout.addStretch()
        return widget

    def _create_prompt_policy_tab(self) -> QWidget:
        """Create Prompt Policy Basic Mode tab (PPS PATCH-09).

        Lets the user pick a non-experimental policy profile (chip selector),
        toggle glossary / context / formatting, select a sampling preset, and
        preview the rendered effective prompt.  State is persisted to QSettings
        under the ``pps/basic/`` namespace.
        """
        from app.infra.translators.prompt_policy import SAMPLING_PROFILES, list_profiles

        widget = QWidget()
        outer = QVBoxLayout(widget)

        title = QLabel("<b>Prompt Policy — Basic Mode</b>")
        title.setTextFormat(Qt.TextFormat.RichText)
        outer.addWidget(title)

        info = QLabel(
            "Select a translation profile and adjust options. "
            "Experimental profiles are not shown here."
        )
        info.setWordWrap(True)
        outer.addWidget(info)

        # ── Profile chip selector ─────────────────────────────────────────
        profile_group = QGroupBox("Translation Profile")
        profile_layout = QVBoxLayout(profile_group)

        self._pps_btn_group = QButtonGroup(widget)
        self._pps_btn_group.setExclusive(True)

        for policy in list_profiles(include_experimental=False):
            btn = QPushButton(policy.name)
            btn.setCheckable(True)
            btn.setToolTip(policy.description)
            btn.setProperty("policy_id", policy.policy_id)
            self._pps_btn_group.addButton(btn)
            profile_layout.addWidget(btn)

        outer.addWidget(profile_group)

        # ── Option toggles ────────────────────────────────────────────────
        options_group = QGroupBox("Options")
        options_layout = QVBoxLayout(options_group)

        self._pps_use_glossary_cb = QCheckBox("Use glossary (inject project terminology)")
        self._pps_use_glossary_cb.setToolTip(
            "When checked: terminology_mode = soft_glossary. "
            "When unchecked: terminology_mode = off."
        )
        self._pps_use_context_cb = QCheckBox("Use context (surrounding sentences)")
        self._pps_use_context_cb.setToolTip(
            "When checked: context_mode = surrounding_sentences (requires context policy). "
            "When unchecked: context_mode = off."
        )
        self._pps_preserve_fmt_cb = QCheckBox("Preserve formatting (placeholder protection)")
        self._pps_preserve_fmt_cb.setToolTip(
            "When checked: formatting_mode = preserve_placeholders. "
            "When unchecked: formatting_mode = plain_text."
        )

        options_layout.addWidget(self._pps_use_glossary_cb)
        options_layout.addWidget(self._pps_use_context_cb)
        options_layout.addWidget(self._pps_preserve_fmt_cb)
        outer.addWidget(options_group)

        # ── Sampling preset ───────────────────────────────────────────────
        sampling_group = QGroupBox("Sampling Preset")
        sampling_layout = QHBoxLayout(sampling_group)

        self._pps_sampling_combo = QComboBox()
        for sp in SAMPLING_PROFILES.values():
            self._pps_sampling_combo.addItem(sp.name, userData=sp.sampling_profile_id)

        sampling_layout.addWidget(QLabel("Preset:"))
        sampling_layout.addWidget(self._pps_sampling_combo)
        sampling_layout.addStretch()
        outer.addWidget(sampling_group)

        # ── Effective Prompt Preview ──────────────────────────────────────
        preview_layout = QHBoxLayout()
        preview_btn = QPushButton("Effective Prompt Preview…")
        preview_btn.setToolTip(
            "Preview the rendered prompt for the selected profile (Layers 1–5)"
        )
        preview_btn.clicked.connect(self._show_effective_prompt_preview)
        preview_layout.addWidget(preview_btn)
        preview_layout.addStretch()
        outer.addLayout(preview_layout)

        outer.addStretch()
        return widget

    def get_pps_options(self) -> dict:
        """Return current Prompt Policy Basic Mode UI state as a dict.

        Keys match ``request.options`` conventions consumed by the provider.

        Returns:
            Dict with keys: policy_id, use_glossary, use_context,
            preserve_formatting, sampling_profile_id.
        """
        checked = self._pps_btn_group.checkedButton()
        policy_id = checked.property("policy_id") if checked else "sentence_ru"
        return {
            "policy_id": policy_id,
            "use_glossary": self._pps_use_glossary_cb.isChecked(),
            "use_context": self._pps_use_context_cb.isChecked(),
            "preserve_formatting": self._pps_preserve_fmt_cb.isChecked(),
            "sampling_profile_id": self._pps_sampling_combo.currentData(),
        }

    def _load_pps_settings(self) -> None:
        """Load PPS Basic Mode settings from QSettings."""
        policy_id = self.settings.value("pps/basic/policy_id", "sentence_ru", type=str)
        for btn in self._pps_btn_group.buttons():
            if btn.property("policy_id") == policy_id:
                btn.setChecked(True)
                break
        else:
            # Fallback: check first button if saved id not found
            buttons = self._pps_btn_group.buttons()
            if buttons:
                buttons[0].setChecked(True)

        self._pps_use_glossary_cb.setChecked(
            self.settings.value("pps/basic/use_glossary", True, type=bool)
        )
        self._pps_use_context_cb.setChecked(
            self.settings.value("pps/basic/use_context", False, type=bool)
        )
        self._pps_preserve_fmt_cb.setChecked(
            self.settings.value("pps/basic/preserve_formatting", True, type=bool)
        )

        sp_id = self.settings.value(
            "pps/basic/sampling_profile_id", "hy_mt_precise_sentence", type=str
        )
        idx = self._pps_sampling_combo.findData(sp_id)
        if idx >= 0:
            self._pps_sampling_combo.setCurrentIndex(idx)

    def _save_pps_settings(self) -> None:
        """Save PPS Basic Mode settings to QSettings."""
        opts = self.get_pps_options()
        self.settings.setValue("pps/basic/policy_id", opts["policy_id"])
        self.settings.setValue("pps/basic/use_glossary", opts["use_glossary"])
        self.settings.setValue("pps/basic/use_context", opts["use_context"])
        self.settings.setValue("pps/basic/preserve_formatting", opts["preserve_formatting"])
        self.settings.setValue("pps/basic/sampling_profile_id", opts["sampling_profile_id"])

    def _show_effective_prompt_preview(self) -> None:
        """Show read-only Effective Prompt Preview dialog for selected policy."""
        from app.infra.translators.prompt_policy import PROMPT_POLICIES, PolicyRenderer

        checked = self._pps_btn_group.checkedButton()
        if not checked:
            QMessageBox.information(self, "No Profile", "Please select a translation profile.")
            return

        policy_id = checked.property("policy_id")
        policy = PROMPT_POLICIES.get(policy_id)
        if not policy:
            return

        renderer = PolicyRenderer()
        sample_text = "שלום עולם"  # sample Hebrew source

        glossary_terms = None
        if self._pps_use_glossary_cb.isChecked():
            glossary_terms = [("שלום", "привет"), ("עולם", "мир")]

        context_items = None
        if self._pps_use_context_cb.isChecked():
            context_items = ["Предыдущее предложение.", "Следующее предложение."]

        preview = renderer.render_effective_preview(
            policy=policy,
            source_text=sample_text,
            glossary_terms=glossary_terms,
            context_items=context_items,
        )

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Effective Prompt Preview — {policy.name}")
        dlg.setMinimumWidth(540)
        dlg.setMinimumHeight(420)
        vlay = QVBoxLayout(dlg)

        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText(preview)
        text_edit.setFontFamily("Courier New")
        vlay.addWidget(text_edit)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)
        vlay.addWidget(close_btn)

        dlg.exec()

    def _create_prompt_audit_tab(self) -> QWidget:
        """Create the Prompt Audit tab (PPS PATCH-05 Debug UI).

        Provides a button to open the PromptAuditDialog and a brief explanation
        of how trace recording is activated.
        """
        from app.ui.prompt_audit_dialog import PromptAuditDialog, PromptAuditPanel

        widget = QWidget()
        layout = QVBoxLayout(widget)

        title = QLabel("<b>Prompt Audit — PPS Debug Mode</b>")
        title.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(title)

        info = QLabel(
            "The Prompt Audit panel records the full EffectivePromptTrace for each translation "
            "request that carries a non-empty <code>trace_id</code>. "
            "Traces show colour-coded semantic layers, applied sampling parameters, "
            "placeholder accounting, and raw vs final output.<br><br>"
            "<b>How to activate trace recording:</b><br>"
            "Set <code>TranslationRequest.trace_id</code> to any non-empty string "
            "(e.g. a segment ID or UUID). The provider will build a trace and store it in "
            "<code>result.meta[\"prompt_policy\"][\"trace\"]</code>. "
            "Call <code>PromptAuditPanel.add_trace(trace)</code> to push it into the history.<br><br>"
            f"<b>History cap:</b> {100} entries (oldest evicted on overflow)."
        )
        info.setWordWrap(True)
        info.setTextFormat(Qt.TextFormat.RichText)
        info.setStyleSheet("color: #334155; font-size: 12px; margin-bottom: 8px;")
        layout.addWidget(info)

        btn_layout = QHBoxLayout()
        open_btn = QPushButton("Open Prompt Audit Window")
        open_btn.setToolTip("Open the full Prompt Audit dialog with history and layer view")
        open_btn.clicked.connect(lambda: PromptAuditDialog(self).exec())
        btn_layout.addWidget(open_btn)

        clear_btn = QPushButton("Clear Trace History")
        clear_btn.setToolTip("Remove all stored traces from the audit history")
        clear_btn.clicked.connect(PromptAuditPanel.clear_history)
        btn_layout.addWidget(clear_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        layout.addStretch()
        return widget

    def _create_gcp_settings(self) -> QWidget:
        """Create Google Cloud Translate advanced settings."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Authentication Section
        auth_group = QGroupBox("Authentication")
        auth_layout = QVBoxLayout(auth_group)

        auth_label = QLabel(
            "Google Cloud Translation API v3 requires Service Account JSON authentication."
        )
        auth_label.setWordWrap(True)
        auth_layout.addWidget(auth_label)

        # Service Account JSON input
        sa_layout = QHBoxLayout()
        sa_layout.addWidget(QLabel("Service Account JSON:"))

        self.gcp_sa_file_btn = QPushButton("Load from File...")
        self.gcp_sa_file_btn.clicked.connect(self._load_gcp_sa_json)
        sa_layout.addWidget(self.gcp_sa_file_btn)

        self.gcp_sa_clear_btn = QPushButton("Clear")
        self.gcp_sa_clear_btn.clicked.connect(self._clear_gcp_sa_json)
        sa_layout.addWidget(self.gcp_sa_clear_btn)

        sa_layout.addStretch()
        auth_layout.addLayout(sa_layout)

        # SA JSON preview
        self.gcp_sa_preview = QLabel("No Service Account JSON configured")
        self.gcp_sa_preview.setStyleSheet("color: gray; font-style: italic;")
        auth_layout.addWidget(self.gcp_sa_preview)

        layout.addWidget(auth_group)

        # Budget Guards Section
        budget_group = QGroupBox("Budget Guards (Fail-Closed)")
        budget_layout = QFormLayout(budget_group)

        self.gcp_max_chars_per_request = QSpinBox()
        self.gcp_max_chars_per_request.setMinimum(100)
        self.gcp_max_chars_per_request.setMaximum(100000)
        self.gcp_max_chars_per_request.setValue(10000)
        self.gcp_max_chars_per_request.setSuffix(" chars")
        budget_layout.addRow("Max chars per request:", self.gcp_max_chars_per_request)

        self.gcp_max_chars_per_day = QSpinBox()
        self.gcp_max_chars_per_day.setMinimum(0)
        self.gcp_max_chars_per_day.setMaximum(10000000)
        self.gcp_max_chars_per_day.setValue(0)
        self.gcp_max_chars_per_day.setSuffix(" chars (0 = unlimited)")
        self.gcp_max_chars_per_day.setSpecialValueText("Unlimited")
        budget_layout.addRow("Max chars per day:", self.gcp_max_chars_per_day)

        self.gcp_max_chars_per_month = QSpinBox()
        self.gcp_max_chars_per_month.setMinimum(0)
        self.gcp_max_chars_per_month.setMaximum(100000000)
        self.gcp_max_chars_per_month.setValue(500000)  # Free tier default
        self.gcp_max_chars_per_month.setSuffix(" chars (0 = unlimited)")
        self.gcp_max_chars_per_month.setSpecialValueText("Unlimited")
        budget_layout.addRow("Max chars per month:", self.gcp_max_chars_per_month)

        self.gcp_max_requests_per_minute = QSpinBox()
        self.gcp_max_requests_per_minute.setMinimum(1)
        self.gcp_max_requests_per_minute.setMaximum(1000)
        self.gcp_max_requests_per_minute.setValue(60)
        self.gcp_max_requests_per_minute.setSuffix(" req/min")
        budget_layout.addRow("Max requests per minute:", self.gcp_max_requests_per_minute)

        self.gcp_max_requests_per_day = QSpinBox()
        self.gcp_max_requests_per_day.setMinimum(0)
        self.gcp_max_requests_per_day.setMaximum(1000000)
        self.gcp_max_requests_per_day.setValue(0)
        self.gcp_max_requests_per_day.setSuffix(" req (0 = unlimited)")
        self.gcp_max_requests_per_day.setSpecialValueText("Unlimited")
        budget_layout.addRow("Max requests per day:", self.gcp_max_requests_per_day)

        layout.addWidget(budget_group)

        # Retry Policy Section
        retry_group = QGroupBox("Retry Policy (429 Rate Limit)")
        retry_layout = QFormLayout(retry_group)

        self.gcp_max_retries = QSpinBox()
        self.gcp_max_retries.setMinimum(0)
        self.gcp_max_retries.setMaximum(10)
        self.gcp_max_retries.setValue(3)
        retry_layout.addRow("Max retries:", self.gcp_max_retries)

        self.gcp_base_backoff_ms = QSpinBox()
        self.gcp_base_backoff_ms.setMinimum(100)
        self.gcp_base_backoff_ms.setMaximum(60000)
        self.gcp_base_backoff_ms.setValue(1000)
        self.gcp_base_backoff_ms.setSuffix(" ms")
        retry_layout.addRow("Base backoff:", self.gcp_base_backoff_ms)

        self.gcp_use_jitter = QCheckBox("Use jitter (prevent thundering herd)")
        self.gcp_use_jitter.setChecked(True)
        retry_layout.addRow("Jitter:", self.gcp_use_jitter)

        layout.addWidget(retry_group)

        # Usage Tracking Section
        usage_group = QGroupBox("Current Usage")
        usage_layout = QVBoxLayout(usage_group)

        self.gcp_usage_label = QLabel("Loading usage statistics...")
        self.gcp_usage_label.setWordWrap(True)
        usage_layout.addWidget(self.gcp_usage_label)

        refresh_btn = QPushButton("Refresh Usage")
        refresh_btn.clicked.connect(self._refresh_gcp_usage)
        usage_layout.addWidget(refresh_btn)

        layout.addWidget(usage_group)

        # Diagnostics Section
        diag_group = QGroupBox("Diagnostics")
        diag_layout = QHBoxLayout(diag_group)

        test_btn = QPushButton("Test API Connection")
        test_btn.clicked.connect(self._test_gcp_connection)
        diag_layout.addWidget(test_btn)

        diag_layout.addStretch()

        layout.addWidget(diag_group)

        # Store widgets for saving
        self.advanced_widgets["google_cloud_translate"] = {
            "max_chars_per_request": self.gcp_max_chars_per_request,
            "max_chars_per_day": self.gcp_max_chars_per_day,
            "max_chars_per_month": self.gcp_max_chars_per_month,
            "max_requests_per_minute": self.gcp_max_requests_per_minute,
            "max_requests_per_day": self.gcp_max_requests_per_day,
            "max_retries": self.gcp_max_retries,
            "base_backoff_ms": self.gcp_base_backoff_ms,
            "use_jitter": self.gcp_use_jitter,
        }

        # Initial usage refresh
        self._refresh_gcp_usage()

        return widget

    def _on_advanced_provider_changed(self, index: int):
        """Handle advanced provider selection change."""
        # For now, only google_cloud_translate is advanced
        # In future, this could switch between different provider settings
        pass

    def _load_gcp_sa_json(self):
        """Load Service Account JSON from file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Service Account JSON",
            "",
            "JSON Files (*.json);;All Files (*)",
        )

        if file_path:
            try:
                with open(file_path, encoding="utf-8") as f:
                    sa_json = f.read()

                # Validate JSON
                import json

                sa_info = json.loads(sa_json)

                # Check required fields
                if "project_id" not in sa_info:
                    QMessageBox.warning(
                        self,
                        "Invalid JSON",
                        "Service Account JSON missing 'project_id' field.",
                    )
                    return

                # Save to CredentialStore
                with DBService.get_instance().get_session() as session:
                    cred_store = CredentialStore(session)
                    self.config_manager._cred_store = cred_store

                    from app.infra.translators.provider_config import (
                        get_service_account_credential_id,
                    )

                    cred_id = get_service_account_credential_id("google_cloud_translate")
                    self.config_manager.set_credential(cred_id, sa_json)

                # Update preview
                project_id = sa_info.get("project_id", "unknown")
                self.gcp_sa_preview.setText(f"✓ Service Account configured (project: {project_id})")
                self.gcp_sa_preview.setStyleSheet("color: green;")

                QMessageBox.information(
                    self,
                    "Success",
                    f"Service Account JSON loaded successfully.\nProject ID: {project_id}",
                )

            except json.JSONDecodeError as e:
                QMessageBox.warning(self, "Invalid JSON", f"Failed to parse JSON: {e}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load Service Account JSON: {e}")

    def _clear_gcp_sa_json(self):
        """Clear Service Account JSON."""
        reply = QMessageBox.question(
            self,
            "Clear Credentials",
            "Are you sure you want to clear the Service Account JSON?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            try:
                with DBService.get_instance().get_session() as session:
                    cred_store = CredentialStore(session)
                    self.config_manager._cred_store = cred_store

                    from app.infra.translators.provider_config import (
                        get_service_account_credential_id,
                    )

                    cred_id = get_service_account_credential_id("google_cloud_translate")
                    self.config_manager.delete_credential(cred_id)

                self.gcp_sa_preview.setText("No Service Account JSON configured")
                self.gcp_sa_preview.setStyleSheet("color: gray; font-style: italic;")

                QMessageBox.information(self, "Success", "Service Account JSON cleared.")

            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to clear credentials: {e}")

    def _refresh_gcp_usage(self):
        """Refresh Google Cloud Translate usage statistics."""
        try:
            with DBService.get_instance().get_session() as session:
                tracker = MTUsageTracker(session)
                summary = tracker.get_usage_summary("google_cloud_translate")

                usage_text = (
                    f"<b>Current Usage:</b><br>"
                    f"• This minute: {summary['minute']['request_count']} requests, "
                    f"{summary['minute']['char_count']} chars<br>"
                    f"• Today: {summary['day']['request_count']} requests, "
                    f"{summary['day']['char_count']} chars<br>"
                    f"• This month: {summary['month']['request_count']} requests, "
                    f"{summary['month']['char_count']} chars"
                )

                self.gcp_usage_label.setText(usage_text)

        except Exception as e:
            self.gcp_usage_label.setText(f"Error loading usage: {e}")

    def _test_gcp_connection(self):
        """Test Google Cloud Translate API connection."""
        try:
            # Get provider from registry
            from app.infra.translators.base_provider import TranslationRequest
            from app.infra.translators.providers_registry import ProvidersRegistry

            registry = ProvidersRegistry()
            provider = registry.get("google_cloud_translate")

            if not provider:
                QMessageBox.warning(
                    self,
                    "Provider Not Found",
                    "Google Cloud Translate provider is not registered.\n"
                    "Please restart the application.",
                )
                return

            # Test translation: "Hello" (English) → Russian
            test_request = TranslationRequest(
                source_text="Hello",
                source_lang="en",
                target_lang="ru",
                trace_id="ui-test-connection",
            )

            # Show progress dialog
            from PyQt6.QtCore import Qt
            from PyQt6.QtWidgets import QProgressDialog

            progress = QProgressDialog(
                "Testing API connection...\nTranslating test phrase...",
                None,
                0,
                0,
                self,
            )
            progress.setWindowTitle("Test Connection")
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.setMinimumDuration(0)
            progress.setCancelButton(None)
            progress.show()

            # Call provider
            result = provider.translate(test_request)

            progress.close()

            # Show result
            if result.is_success:
                QMessageBox.information(
                    self,
                    "Connection Successful",
                    f"✓ Google Cloud Translate API connection successful!\n\n"
                    f"Test translation:\n"
                    f'  "Hello" (en) → "{result.translated_text}" (ru)\n\n'
                    f"Latency: {result.latency_ms}ms\n"
                    f"Provider: {result.provider_id}",
                )
            else:
                error_details = f"Error: {result.error_message}\n\n"
                if result.error_kind:
                    error_details += f"Error type: {result.error_kind.value}\n"
                error_details += f"Latency: {result.latency_ms}ms"

                QMessageBox.critical(
                    self,
                    "Connection Failed",
                    f"✗ Google Cloud Translate API connection failed.\n\n{error_details}",
                )

        except Exception as e:
            QMessageBox.critical(
                self,
                "Test Error",
                f"Failed to test API connection:\n\n{e}",
            )

    def _load_settings(self):
        """Load settings from QSettings."""
        # Load master enable switch (default True)
        master_enabled = self.settings.value("mt/providers/enabled", True, type=bool)
        self.master_enable_checkbox.setChecked(master_enabled)

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

        # Load advanced settings for google_cloud_translate
        self._load_gcp_advanced_settings()

        # Load PPS Basic Mode settings
        self._load_pps_settings()

    def _load_gcp_advanced_settings(self):
        """Load Google Cloud Translate advanced settings."""
        config = self.config_manager.load_config("google_cloud_translate")

        # Load limits
        self.gcp_max_chars_per_request.setValue(config.limits.max_chars_per_request)
        self.gcp_max_chars_per_day.setValue(config.limits.max_chars_per_day or 0)
        self.gcp_max_chars_per_month.setValue(config.limits.max_chars_per_month or 0)
        self.gcp_max_requests_per_minute.setValue(config.limits.max_requests_per_minute)
        self.gcp_max_requests_per_day.setValue(config.limits.max_requests_per_day or 0)

        # Load retry policy
        self.gcp_max_retries.setValue(config.retry.max_retries)
        self.gcp_base_backoff_ms.setValue(config.retry.base_backoff_ms)
        self.gcp_use_jitter.setChecked(config.retry.use_jitter)

        # Check if Service Account JSON is configured
        if config.auth.service_account_credential_id:
            try:
                with DBService.get_instance().get_session() as session:
                    cred_store = CredentialStore(session)
                    self.config_manager._cred_store = cred_store

                    sa_json = self.config_manager.get_credential(
                        config.auth.service_account_credential_id
                    )

                    if sa_json:
                        import json

                        sa_info = json.loads(sa_json)
                        project_id = sa_info.get("project_id", "unknown")
                        self.gcp_sa_preview.setText(
                            f"✓ Service Account configured (project: {project_id})"
                        )
                        self.gcp_sa_preview.setStyleSheet("color: green;")
                    else:
                        self.gcp_sa_preview.setText("No Service Account JSON configured")
                        self.gcp_sa_preview.setStyleSheet("color: gray; font-style: italic;")

            except Exception as e:
                self.gcp_sa_preview.setText(f"Error loading credentials: {e}")
                self.gcp_sa_preview.setStyleSheet("color: red;")

    def _save_settings(self):
        """Save settings to QSettings."""
        # Save master enable switch
        master_enabled = self.master_enable_checkbox.isChecked()
        self.settings.setValue("mt/providers/enabled", master_enabled)

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

        # Save advanced settings for google_cloud_translate
        self._save_gcp_advanced_settings()

        # Save PPS Basic Mode settings
        self._save_pps_settings()

        self.settings.sync()

    def _save_gcp_advanced_settings(self):
        """Save Google Cloud Translate advanced settings."""
        from app.infra.translators.provider_config import (
            ProviderConfig,
            get_service_account_credential_id,
        )

        # Build config object
        config = ProviderConfig(
            provider_id="google_cloud_translate",
            auth=ProviderAuthConfig(
                mode=ProviderAuthMode.SERVICE_ACCOUNT_JSON,
                service_account_credential_id=get_service_account_credential_id(
                    "google_cloud_translate"
                ),
            ),
            limits=ProviderLimitsConfig(
                max_chars_per_request=self.gcp_max_chars_per_request.value(),
                max_chars_per_day=self.gcp_max_chars_per_day.value() or None,
                max_chars_per_month=self.gcp_max_chars_per_month.value() or None,
                max_requests_per_minute=self.gcp_max_requests_per_minute.value(),
                max_requests_per_day=self.gcp_max_requests_per_day.value() or None,
                fail_closed=True,  # Always fail-closed for official APIs
            ),
            retry=ProviderRetryPolicy(
                max_retries=self.gcp_max_retries.value(),
                base_backoff_ms=self.gcp_base_backoff_ms.value(),
                use_jitter=self.gcp_use_jitter.isChecked(),
            ),
        )

        # Save to QSettings (via ProviderConfigManager)
        self.config_manager.save_config(config)

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
            # Restore master enable switch (default True)
            self.master_enable_checkbox.setChecked(True)

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


def load_pps_basic_options(settings: QSettings | None = None) -> dict:
    """Read PPS Basic Mode settings from QSettings and return as request options dict.

    Returns a dict suitable for passing as ``TranslationRequest.options``.
    Only the keys relevant to local HY-MT providers are included; all other
    providers silently ignore unknown options keys.

    Keys returned:
        ``prompt_policy_id``  — active policy (consumed by TranslationRouter).
        ``use_glossary``      — bool; False disables prompt injection + postprocess.
        ``sampling_profile_id`` — str; overrides policy's default sampling preset.

    Args:
        settings: Optional QSettings instance (uses default QSettings() if None).
            Pass an explicit instance in tests to avoid global QSettings state.

    Returns:
        Dict with PPS basic options from QSettings (with sane defaults if not set).
    """
    s: QSettings = settings if settings is not None else QSettings()
    return {
        "prompt_policy_id": s.value("pps/basic/policy_id", "sentence_ru", type=str),
        "use_glossary": s.value("pps/basic/use_glossary", True, type=bool),
        "sampling_profile_id": s.value(
            "pps/basic/sampling_profile_id", "hy_mt_precise_sentence", type=str
        ),
    }
