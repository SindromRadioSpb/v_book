"""Advanced Policy Editor Widget — PPS PATCH-10.

Provides a full policy editor for HY-MT prompt policies:
- Policy dropdown: full registry including experimental + custom policies
- Role / Task / Output editors gated by allow_user_edit_* flags
- Mode selectors (terminology, context, formatting, placeholder, sampling)
- [↺ Reset] buttons per text editor
- [Save as Custom] → creates is_custom=True copy with new policy_id
- [Export] → saves effective policy to YAML (falls back to JSON)
- "Use Advanced Mode" toggle → overrides Basic Mode profile selection at runtime

Custom policy persistence:
  QSettings key ``pps/custom_policies`` — JSON array of serialised policy dicts.
  Loaded at widget construction; saved after every [Save as Custom].

Runtime integration:
  When "Use Advanced Mode" is checked, :func:`load_pps_request_options` (in
  provider_settings_dialog) returns advanced options instead of basic ones.
  Advanced options carry: ``prompt_policy_id``, ``use_glossary``,
  ``sampling_profile_id``.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.infra.translators.prompt_policy import (
    PROMPT_POLICIES,
    SAMPLING_PROFILES,
    ContentKind,
    ContextMode,
    FormattingMode,
    PlaceholderMode,
    PromptPolicy,
    TerminologyMode,
)

logger = logging.getLogger(__name__)

# QSettings key for persisted custom policies (JSON array of dicts)
_CUSTOM_POLICIES_KEY = "pps/custom_policies"

# QSettings keys for advanced mode state
_ADV_ACTIVE_KEY = "pps/advanced/active"
_ADV_POLICY_KEY = "pps/advanced/policy_id"
_ADV_TERMINOLOGY_KEY = "pps/advanced/terminology_mode"
_ADV_SAMPLING_KEY = "pps/advanced/sampling_profile_id"

# Fields serialised for custom policy persistence (excludes runtime metadata)
_SERIALISABLE_FIELDS: tuple[str, ...] = (
    "policy_id",
    "name",
    "description",
    "content_kind",
    "source_lang",
    "target_lang",
    "role_instruction",
    "task_instruction",
    "output_policy",
    "terminology_mode",
    "context_mode",
    "formatting_mode",
    "placeholder_mode",
    "sampling_profile_id",
    "template_profile_id",
    "allow_user_edit_role",
    "allow_user_edit_task",
    "allow_user_edit_output_policy",
    "is_custom",
    "is_builtin",
    "experimental",
    "enabled",
    "version",
    "max_glossary_items",
    "max_context_items",
    "max_input_chars",
)


# ---------------------------------------------------------------------------
# Serialisation helpers (module-level for testability)
# ---------------------------------------------------------------------------


def policy_to_dict(policy: PromptPolicy) -> dict:
    """Serialise a PromptPolicy to a plain dict (all string/bool/int/None values).

    Enum values are converted to their string form via ``str()``.
    Only fields listed in ``_SERIALISABLE_FIELDS`` are included.

    Args:
        policy: PromptPolicy to serialise.

    Returns:
        Serialisable dict suitable for JSON persistence.
    """
    result: dict = {}
    for fname in _SERIALISABLE_FIELDS:
        val = getattr(policy, fname, None)
        if hasattr(val, "value"):  # StrEnum / Enum
            result[fname] = str(val)
        else:
            result[fname] = val
    return result


def dict_to_policy(d: dict) -> PromptPolicy | None:
    """Deserialise a dict to a PromptPolicy.

    Silently returns ``None`` if required fields are missing or invalid,
    so that corrupt persisted data does not crash the application.

    Args:
        d: Dict as produced by :func:`policy_to_dict`.

    Returns:
        PromptPolicy, or ``None`` on failure.
    """
    try:
        return PromptPolicy(
            policy_id=d["policy_id"],
            name=d["name"],
            content_kind=ContentKind(d.get("content_kind", "sentence")),
            source_lang=d.get("source_lang", "he"),
            target_lang=d.get("target_lang", "ru"),
            role_instruction=d.get("role_instruction", ""),
            task_instruction=d.get("task_instruction", ""),
            output_policy=d.get("output_policy", ""),
            terminology_mode=TerminologyMode(d.get("terminology_mode", "soft_glossary")),
            context_mode=ContextMode(d.get("context_mode", "off")),
            formatting_mode=FormattingMode(d.get("formatting_mode", "preserve_placeholders")),
            placeholder_mode=PlaceholderMode(
                d.get("placeholder_mode", "protect_known_placeholders")
            ),
            sampling_profile_id=d.get("sampling_profile_id", "hy_mt_precise_sentence"),
            template_profile_id=d.get("template_profile_id", "hy_mt_standard_observed"),
            description=d.get("description", ""),
            enabled=d.get("enabled", True),
            version=d.get("version", "1.0.0"),
            allow_user_edit_role=d.get("allow_user_edit_role", True),
            allow_user_edit_task=d.get("allow_user_edit_task", True),
            allow_user_edit_output_policy=d.get("allow_user_edit_output_policy", True),
            is_custom=d.get("is_custom", True),
            is_builtin=d.get("is_builtin", False),
            experimental=d.get("experimental", False),
            max_glossary_items=d.get("max_glossary_items", 20),
            max_context_items=d.get("max_context_items"),
            max_input_chars=d.get("max_input_chars"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("dict_to_policy: failed to deserialise policy %r: %s", d.get("policy_id"), exc)
        return None


def clone_policy_as_custom(source: PromptPolicy, **overrides) -> PromptPolicy:
    """Create an independent custom copy of ``source`` with a new unique policy_id.

    The copy has ``is_custom=True``, ``is_builtin=False``, and
    ``policy_id = "{source.policy_id}_custom_{uuid8}"``.
    Caller may pass keyword overrides for any PromptPolicy field.

    Args:
        source: Built-in or existing policy to clone.
        **overrides: Any PromptPolicy field values to override in the copy.

    Returns:
        New PromptPolicy with ``is_custom=True``.
    """
    uid8 = uuid.uuid4().hex[:8]
    base = policy_to_dict(source)
    base.update(
        {
            "policy_id": f"{source.policy_id}_custom_{uid8}",
            "name": f"{source.name} (Custom)",
            "is_custom": True,
            "is_builtin": False,
            # PATCH-10c: custom policies are explicitly user-selected — not experimental.
            "experimental": False,
            # Custom copies are always fully editable regardless of source's allow_user_edit_*
            # flags. Built-ins lock those flags to False to protect immutability; custom copies
            # have no such restriction — the user created them to edit.
            "allow_user_edit_role": True,
            "allow_user_edit_task": True,
            "allow_user_edit_output_policy": True,
        }
    )
    base.update({k: (str(v) if hasattr(v, "value") else v) for k, v in overrides.items()})
    return dict_to_policy(base)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# AdvancedPolicyEditorWidget
# ---------------------------------------------------------------------------


class AdvancedPolicyEditorWidget(QWidget):
    """Standalone widget for Advanced Mode policy editing (PPS PATCH-10).

    Intended to be embedded as a tab inside ``ProviderSettingsDialog``.
    State is persisted via the ``QSettings`` instance passed at construction
    (defaults to ``QSettings()`` for production use; injectable for tests).
    """

    def __init__(self, parent: QWidget | None = None, settings: QSettings | None = None) -> None:
        """Initialise the widget.

        Args:
            parent: Optional parent widget.
            settings: QSettings instance for state persistence.
                Pass an explicit instance in tests to avoid global state.
        """
        super().__init__(parent)
        self._settings: QSettings = settings if settings is not None else QSettings()
        self._custom_policies: list[PromptPolicy] = []
        self._base_policy: PromptPolicy | None = None  # unedited source for Reset

        self._load_custom_policies_from_settings()
        self._init_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _init_ui(self) -> None:
        """Build the complete Advanced Mode editor UI."""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)

        # ── "Use Advanced Mode" toggle ────────────────────────────────
        self._active_cb = QCheckBox(
            "Use Advanced Mode (overrides Basic Mode profile selection)"
        )
        self._active_cb.setToolTip(
            "When checked, the policy selected below overrides the Basic Mode chip. "
            "Uncheck to fall back to Basic Mode settings."
        )
        outer.addWidget(self._active_cb)

        # ── Scrollable content area ───────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        content = QWidget()
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(0, 0, 4, 0)

        self._build_policy_selector()
        self._build_text_editors()
        self._build_mode_selectors()
        self._build_action_buttons()
        self._content_layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll)

        # Populate dropdown now (requires all widgets to exist)
        self._populate_policy_combo()

        # Load first policy into editors
        if self._policy_combo.count() > 0:
            self._policy_combo.setCurrentIndex(0)
            self._on_policy_selected(0)

    def _build_policy_selector(self) -> None:
        """Build policy dropdown row."""
        row = QHBoxLayout()
        row.addWidget(QLabel("Policy:"))

        self._policy_combo = QComboBox()
        self._policy_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._policy_combo.currentIndexChanged.connect(self._on_policy_selected)
        row.addWidget(self._policy_combo)

        self._content_layout.addLayout(row)

    def _build_text_editors(self) -> None:
        """Build Role / Task / Output text editors with Reset buttons."""
        for attr, label, allow_flag in (
            ("_role_edit", "Role Instruction", "allow_user_edit_role"),
            ("_task_edit", "Task Instruction", "allow_user_edit_task"),
            ("_output_edit", "Output Policy", "allow_user_edit_output_policy"),
        ):
            group = QGroupBox(label)
            vlay = QVBoxLayout(group)

            edit = QPlainTextEdit()
            edit.setMaximumHeight(90)
            edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            edit.setReadOnly(True)  # starts read-only; unlocked by _load_policy_into_editors
            setattr(self, attr, edit)
            vlay.addWidget(edit)

            reset_btn = QPushButton("↺ Reset")
            reset_btn.setToolTip(f"Restore {label} to the built-in / base value")
            reset_btn.setMaximumWidth(80)
            reset_attr = f"_reset_{attr.lstrip('_').split('_')[0]}_btn"
            setattr(self, reset_attr, reset_btn)

            btn_row = QHBoxLayout()
            btn_row.addStretch()
            btn_row.addWidget(reset_btn)
            vlay.addLayout(btn_row)

            self._content_layout.addWidget(group)

        # Wire Reset buttons (after all attrs set)
        self._reset_role_btn.clicked.connect(self._on_reset_role)
        self._reset_task_btn.clicked.connect(self._on_reset_task)
        self._reset_output_btn.clicked.connect(self._on_reset_output)

    def _build_mode_selectors(self) -> None:
        """Build mode selector comboboxes (terminology, context, formatting, placeholder, sampling)."""
        group = QGroupBox("Modes")
        form = QFormLayout(group)

        self._terminology_combo = self._make_enum_combo(TerminologyMode)
        self._context_combo = self._make_enum_combo(ContextMode)
        self._formatting_combo = self._make_enum_combo(FormattingMode)
        self._placeholder_combo = self._make_enum_combo(PlaceholderMode)

        self._sampling_combo = QComboBox()
        for sp in SAMPLING_PROFILES.values():
            self._sampling_combo.addItem(sp.name, userData=sp.sampling_profile_id)

        form.addRow("Terminology mode:", self._terminology_combo)
        form.addRow("Context mode:", self._context_combo)
        form.addRow("Formatting mode:", self._formatting_combo)
        form.addRow("Placeholder mode:", self._placeholder_combo)
        form.addRow("Sampling preset:", self._sampling_combo)

        self._content_layout.addWidget(group)

    def _build_action_buttons(self) -> None:
        """Build [Save as Custom], [Export] and [Delete] action buttons."""
        btn_row = QHBoxLayout()

        self._save_custom_btn = QPushButton("Save as Custom")
        self._save_custom_btn.setToolTip(
            "Create an independent custom copy of this policy (is_custom=True, new policy_id). "
            "Built-in policies remain immutable."
        )
        self._save_custom_btn.clicked.connect(self._on_save_as_custom)
        btn_row.addWidget(self._save_custom_btn)

        self._export_btn = QPushButton("Export…")
        self._export_btn.setToolTip("Export the current policy to a YAML file")
        self._export_btn.clicked.connect(self._on_export)
        btn_row.addWidget(self._export_btn)

        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setToolTip(
            "Permanently delete this custom policy.\n"
            "Built-in policies cannot be deleted."
        )
        self._delete_btn.setEnabled(False)  # enabled only when a custom policy is selected
        self._delete_btn.clicked.connect(self._on_delete_custom)
        btn_row.addWidget(self._delete_btn)

        btn_row.addStretch()
        self._content_layout.addLayout(btn_row)

    @staticmethod
    def _make_enum_combo(enum_cls) -> QComboBox:
        """Build a QComboBox populated with all values of an StrEnum class.

        Args:
            enum_cls: StrEnum subclass (TerminologyMode, ContextMode, etc.).

        Returns:
            Populated QComboBox with display name as text and enum string as userData.
        """
        combo = QComboBox()
        for member in enum_cls:
            label = member.value.replace("_", " ").title()
            combo.addItem(label, userData=str(member))
        return combo

    # ------------------------------------------------------------------
    # Dropdown population
    # ------------------------------------------------------------------

    def _populate_policy_combo(self) -> None:
        """Populate policy dropdown from full registry + custom policies.

        Order: built-ins (sorted by policy_id) first, then custom policies.
        Label format: ``{name} [{policy_id}]``
        """
        self._policy_combo.blockSignals(True)
        saved_id = self._policy_combo.currentData()
        self._policy_combo.clear()

        # Built-in policies (all, including experimental)
        for policy in sorted(PROMPT_POLICIES.values(), key=lambda p: p.policy_id):
            suffix = " [exp]" if policy.experimental else ""
            label = f"{policy.name}{suffix} [{policy.policy_id}]"
            self._policy_combo.addItem(label, userData=policy.policy_id)

        # Custom policies
        for policy in self._custom_policies:
            label = f"{policy.name} [{policy.policy_id}]"
            self._policy_combo.addItem(label, userData=policy.policy_id)

        # Restore previous selection if possible
        if saved_id:
            idx = self._policy_combo.findData(saved_id)
            if idx >= 0:
                self._policy_combo.setCurrentIndex(idx)

        self._policy_combo.blockSignals(False)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_policy_selected(self, index: int) -> None:
        """Load the selected policy into all editor widgets."""
        policy_id = self._policy_combo.currentData()
        policy = self._resolve_policy(policy_id)
        if policy is None:
            return
        self._base_policy = policy
        self._load_policy_into_editors(policy)
        self._update_delete_button()

    def _load_policy_into_editors(self, policy: PromptPolicy) -> None:
        """Populate all editor widgets from a PromptPolicy instance.

        Args:
            policy: Policy whose values should be reflected in the UI.
        """
        # Text editors — enable only when allow_user_edit_* is True
        self._role_edit.setPlainText(policy.role_instruction)
        self._role_edit.setReadOnly(not policy.allow_user_edit_role)

        self._task_edit.setPlainText(policy.task_instruction)
        self._task_edit.setReadOnly(not policy.allow_user_edit_task)

        self._output_edit.setPlainText(policy.output_policy)
        self._output_edit.setReadOnly(not policy.allow_user_edit_output_policy)

        # Reset buttons active only when editor is editable
        self._reset_role_btn.setEnabled(policy.allow_user_edit_role)
        self._reset_task_btn.setEnabled(policy.allow_user_edit_task)
        self._reset_output_btn.setEnabled(policy.allow_user_edit_output_policy)

        # Mode selectors
        self._set_combo_by_data(self._terminology_combo, str(policy.terminology_mode))
        self._set_combo_by_data(self._context_combo, str(policy.context_mode))
        self._set_combo_by_data(self._formatting_combo, str(policy.formatting_mode))
        self._set_combo_by_data(self._placeholder_combo, str(policy.placeholder_mode))
        self._set_combo_by_data(self._sampling_combo, policy.sampling_profile_id)

    def _on_reset_role(self) -> None:
        """Restore role_instruction to base policy value."""
        if self._base_policy:
            self._role_edit.setPlainText(self._base_policy.role_instruction)

    def _on_reset_task(self) -> None:
        """Restore task_instruction to base policy value."""
        if self._base_policy:
            self._task_edit.setPlainText(self._base_policy.task_instruction)

    def _on_reset_output(self) -> None:
        """Restore output_policy to base policy value."""
        if self._base_policy:
            self._output_edit.setPlainText(self._base_policy.output_policy)

    # ------------------------------------------------------------------
    # Delete custom policy
    # ------------------------------------------------------------------

    def _is_current_policy_custom(self) -> bool:
        """Return True when the currently selected dropdown item is a custom policy."""
        policy_id = self._policy_combo.currentData()
        policy = self._resolve_policy(policy_id)
        return policy is not None and policy.is_custom

    def _update_delete_button(self) -> None:
        """Enable the Delete button only when the selected policy is custom."""
        self._delete_btn.setEnabled(self._is_current_policy_custom())

    def _on_delete_custom(self) -> None:
        """Delete the currently selected custom policy after user confirmation.

        Removes the policy from:
        - ``self._custom_policies`` (in-memory list)
        - QSettings ``pps/custom_policies``
        - The runtime ``_CUSTOM_POLICIES`` registry (via :func:`unregister_custom_policy`)
        - The policy dropdown

        After deletion the dropdown selects the first available built-in policy.
        Built-in policies cannot be deleted; the method returns immediately if the
        current selection is not a custom policy.
        """
        policy_id: str | None = self._policy_combo.currentData()
        policy = self._resolve_policy(policy_id)
        if policy is None or not policy.is_custom:
            return  # guard: never delete a built-in

        reply = QMessageBox.question(
            self,
            "Delete Custom Policy",
            f"Delete custom policy '{policy.name}'?\n\nID: {policy.policy_id}\n\n"
            "This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Remove from in-memory list and persist
        self._custom_policies = [p for p in self._custom_policies if p.policy_id != policy_id]
        self._save_custom_policies_to_settings()

        # Remove from runtime registry
        from app.infra.translators.prompt_policy import unregister_custom_policy

        unregister_custom_policy(policy_id)  # type: ignore[arg-type]

        # Rebuild dropdown; select first built-in as visual fallback
        self._populate_policy_combo()
        if self._policy_combo.count() > 0:
            self._policy_combo.setCurrentIndex(0)
            self._on_policy_selected(0)

    def _on_save_as_custom(self) -> None:
        """Create an independent custom policy from the current editor state."""
        base = self._base_policy
        if base is None:
            return

        # Always capture all text editor content as overrides for the new custom copy.
        # For read-only editors (built-in source), the text matches the base policy — no
        # semantic change.  For editable editors (custom source), this captures user edits.
        overrides: dict = {
            "role_instruction": self._role_edit.toPlainText().strip(),
            "task_instruction": self._task_edit.toPlainText().strip(),
            "output_policy": self._output_edit.toPlainText().strip(),
            "terminology_mode": self._terminology_combo.currentData(),
            "context_mode": self._context_combo.currentData(),
            "formatting_mode": self._formatting_combo.currentData(),
            "placeholder_mode": self._placeholder_combo.currentData(),
            "sampling_profile_id": self._sampling_combo.currentData(),
        }

        custom = clone_policy_as_custom(base, **overrides)
        if custom is None:
            QMessageBox.critical(self, "Error", "Failed to create custom policy.")
            return

        self._custom_policies.append(custom)
        self._save_custom_policies_to_settings()
        self._populate_policy_combo()

        # Select the newly created policy
        idx = self._policy_combo.findData(custom.policy_id)
        if idx >= 0:
            self._policy_combo.setCurrentIndex(idx)

        QMessageBox.information(
            self,
            "Saved",
            f"Custom policy created:\n{custom.name}\nID: {custom.policy_id}",
        )

    def _on_export(self) -> None:
        """Export the current effective policy to a YAML (or JSON) file."""
        base = self._base_policy
        if base is None:
            return

        # Build export dict from editors (takes precedence over base for editable fields)
        d = policy_to_dict(base)
        if base.allow_user_edit_role:
            d["role_instruction"] = self._role_edit.toPlainText().strip()
        if base.allow_user_edit_task:
            d["task_instruction"] = self._task_edit.toPlainText().strip()
        if base.allow_user_edit_output_policy:
            d["output_policy"] = self._output_edit.toPlainText().strip()
        d["terminology_mode"] = self._terminology_combo.currentData()
        d["context_mode"] = self._context_combo.currentData()
        d["formatting_mode"] = self._formatting_combo.currentData()
        d["sampling_profile_id"] = self._sampling_combo.currentData()
        d["exported_at"] = datetime.now(UTC).isoformat()

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Policy",
            f"{base.policy_id}_export.yaml",
            "YAML Files (*.yaml *.yml);;JSON Files (*.json);;All Files (*)",
        )
        if not path:
            return

        try:
            text = _serialise_for_export(d, path)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            QMessageBox.information(self, "Exported", f"Policy exported to:\n{path}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Export Error", f"Failed to export policy:\n{exc}")

    # ------------------------------------------------------------------
    # Custom policy persistence
    # ------------------------------------------------------------------

    def _load_custom_policies_from_settings(self) -> None:
        """Load custom policies from QSettings (JSON array)."""
        raw: str = self._settings.value(_CUSTOM_POLICIES_KEY, "[]", type=str)
        try:
            data: list[dict] = json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to parse custom policies JSON: %s", exc)
            data = []

        self._custom_policies = []
        for d in data:
            policy = dict_to_policy(d)
            if policy is not None:
                self._custom_policies.append(policy)

    def _save_custom_policies_to_settings(self) -> None:
        """Persist custom policies to QSettings as JSON array."""
        data = [policy_to_dict(p) for p in self._custom_policies]
        self._settings.setValue(_CUSTOM_POLICIES_KEY, json.dumps(data, ensure_ascii=False))
        self._settings.sync()

    # ------------------------------------------------------------------
    # State load / save (called by ProviderSettingsDialog)
    # ------------------------------------------------------------------

    def load_settings(self) -> None:
        """Restore Advanced Mode state from QSettings."""
        active = self._settings.value(_ADV_ACTIVE_KEY, False, type=bool)
        self._active_cb.setChecked(active)

        policy_id = self._settings.value(_ADV_POLICY_KEY, "", type=str)
        if policy_id:
            idx = self._policy_combo.findData(policy_id)
            if idx >= 0:
                self._policy_combo.setCurrentIndex(idx)

        terminology = self._settings.value(_ADV_TERMINOLOGY_KEY, "", type=str)
        if terminology:
            self._set_combo_by_data(self._terminology_combo, terminology)

        sampling = self._settings.value(_ADV_SAMPLING_KEY, "", type=str)
        if sampling:
            self._set_combo_by_data(self._sampling_combo, sampling)

    def save_settings(self) -> None:
        """Persist Advanced Mode state to QSettings."""
        self._settings.setValue(_ADV_ACTIVE_KEY, self._active_cb.isChecked())
        self._settings.setValue(_ADV_POLICY_KEY, self._policy_combo.currentData() or "")
        self._settings.setValue(_ADV_TERMINOLOGY_KEY, self._terminology_combo.currentData() or "")
        self._settings.setValue(_ADV_SAMPLING_KEY, self._sampling_combo.currentData() or "")

    # ------------------------------------------------------------------
    # Runtime options interface
    # ------------------------------------------------------------------

    def is_advanced_active(self) -> bool:
        """Return True when Advanced Mode is checked (overrides Basic Mode)."""
        return self._active_cb.isChecked()

    def get_advanced_options(self) -> dict:
        """Return options dict for TranslationRequest when Advanced Mode is active.

        Keys:
            ``prompt_policy_id`` — selected policy (built-in or custom).
            ``use_glossary``     — derived from current terminology_mode selector.
            ``sampling_profile_id`` — from sampling selector.

        Returns:
            Empty dict when Advanced Mode is not active.
        """
        if not self._active_cb.isChecked():
            return {}
        terminology_str: str = self._terminology_combo.currentData() or str(TerminologyMode.SOFT_GLOSSARY)
        return {
            "prompt_policy_id": self._policy_combo.currentData() or "sentence_ru",
            "use_glossary": terminology_str != str(TerminologyMode.OFF),
            "sampling_profile_id": self._sampling_combo.currentData() or "hy_mt_precise_sentence",
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_policy(self, policy_id: str | None) -> PromptPolicy | None:
        """Look up a policy by ID from built-ins or custom list."""
        if not policy_id:
            return None
        if policy_id in PROMPT_POLICIES:
            return PROMPT_POLICIES[policy_id]
        for p in self._custom_policies:
            if p.policy_id == policy_id:
                return p
        return None

    @staticmethod
    def _set_combo_by_data(combo: QComboBox, data: str) -> None:
        """Select a QComboBox item whose userData matches ``data``."""
        idx = combo.findData(data)
        if idx >= 0:
            combo.setCurrentIndex(idx)


# ---------------------------------------------------------------------------
# YAML / JSON export helper
# ---------------------------------------------------------------------------


def _serialise_for_export(d: dict, path: str) -> str:
    """Serialise ``d`` to YAML or JSON depending on file extension.

    Uses ``yaml.dump`` when pyyaml is available; falls back to ``json.dumps``
    with indent=2 (which is valid YAML for simple dicts).

    Args:
        d: Serialisable dict.
        path: Target file path (extension determines format).

    Returns:
        String content to write to the file.
    """
    if path.lower().endswith((".yaml", ".yml")):
        try:
            import yaml  # type: ignore[import-untyped]  # pyyaml; available in venv (6.0.3)

            return yaml.dump(d, allow_unicode=True, sort_keys=False, default_flow_style=False)
        except ImportError:
            pass  # fall through to JSON
    return json.dumps(d, ensure_ascii=False, indent=2)
