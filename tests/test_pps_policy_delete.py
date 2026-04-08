"""PPS — Delete custom policy from Policy Editor.

Tests verify that:
- Delete button is enabled only for custom policies.
- Built-in policies cannot be deleted (button disabled + guard in slot).
- Deletion removes the policy from dropdown, QSettings, in-memory list,
  and runtime registry.
- Deleting the active policy switches UI to a built-in fallback.
- Deleting the last custom policy leaves the editor in a valid state.
- Confirm dialog is shown; cancellation leaves everything intact.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QMessageBox

from app.infra.translators.prompt_policy import (
    PROMPT_POLICIES,
    clear_custom_policies,
    list_custom_policy_ids,
)
from app.ui.advanced_policy_editor import (
    AdvancedPolicyEditorWidget,
    clone_policy_as_custom,
    policy_to_dict,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _isolated_settings(name: str) -> QSettings:
    s = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "HDLE_Test", name)
    s.clear()
    s.sync()
    return s


def _add_custom_to_widget(widget: AdvancedPolicyEditorWidget) -> str:
    """Programmatically create and register a custom policy in the widget.

    Returns:
        policy_id of the newly created custom policy.
    """
    source = PROMPT_POLICIES["sentence_ru"]
    custom = clone_policy_as_custom(source, task_instruction="custom task for delete tests")
    widget._custom_policies.append(custom)
    widget._save_custom_policies_to_settings()
    widget._populate_policy_combo()
    return custom.policy_id


def _select_policy(widget: AdvancedPolicyEditorWidget, policy_id: str) -> bool:
    """Select a policy by ID in the dropdown. Returns True if found."""
    idx = widget._policy_combo.findData(policy_id)
    if idx < 0:
        return False
    widget._policy_combo.setCurrentIndex(idx)
    widget._on_policy_selected(idx)
    return True


@pytest.fixture(autouse=True)
def _cleanup():
    """Clean runtime registry before and after every test."""
    clear_custom_policies()
    yield
    clear_custom_policies()


@pytest.fixture
def settings():
    s = _isolated_settings("pps_delete_test")
    yield s
    s.clear()
    s.sync()


@pytest.fixture
def editor(qtbot, settings):
    w = AdvancedPolicyEditorWidget(settings=settings)
    qtbot.addWidget(w)
    yield w


# ---------------------------------------------------------------------------
# Delete button state
# ---------------------------------------------------------------------------


def test_delete_button_disabled_for_builtin(editor):
    """Delete button is disabled when a built-in policy is selected."""
    # Default selection is first built-in
    assert not editor._delete_btn.isEnabled()


def test_delete_button_enabled_for_custom(editor, qtbot):
    """Delete button is enabled when a custom policy is selected."""
    custom_id = _add_custom_to_widget(editor)
    found = _select_policy(editor, custom_id)
    assert found, "Custom policy not found in dropdown"
    assert editor._delete_btn.isEnabled()


def test_delete_button_disabled_after_switching_back_to_builtin(editor, qtbot):
    """Delete button becomes disabled when user switches back to a built-in."""
    custom_id = _add_custom_to_widget(editor)
    _select_policy(editor, custom_id)
    assert editor._delete_btn.isEnabled()

    # Switch to first built-in
    editor._policy_combo.setCurrentIndex(0)
    editor._on_policy_selected(0)
    assert not editor._delete_btn.isEnabled()


# ---------------------------------------------------------------------------
# Guard: cannot delete built-in via slot
# ---------------------------------------------------------------------------


def test_guard_builtin_selected_slot_is_noop(editor):
    """_on_delete_custom() with a built-in selected does nothing (no QMessageBox)."""
    # Select first built-in
    editor._policy_combo.setCurrentIndex(0)
    editor._on_policy_selected(0)

    # Count combo items before
    count_before = editor._policy_combo.count()

    with patch("app.ui.advanced_policy_editor.QMessageBox") as mock_msgbox:
        editor._on_delete_custom()
        # QMessageBox.question must NOT have been called
        mock_msgbox.question.assert_not_called()

    # Nothing changed
    assert editor._policy_combo.count() == count_before


# ---------------------------------------------------------------------------
# Successful deletion
# ---------------------------------------------------------------------------


def test_delete_removes_from_dropdown(editor, qtbot):
    """After delete, the custom policy is no longer present in the dropdown."""
    custom_id = _add_custom_to_widget(editor)
    _select_policy(editor, custom_id)

    with patch(
        "app.ui.advanced_policy_editor.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        editor._on_delete_custom()

    assert editor._policy_combo.findData(custom_id) == -1


def test_delete_removes_from_in_memory_list(editor, qtbot):
    """After delete, the custom policy is removed from widget's _custom_policies list."""
    custom_id = _add_custom_to_widget(editor)
    _select_policy(editor, custom_id)

    with patch(
        "app.ui.advanced_policy_editor.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        editor._on_delete_custom()

    remaining_ids = [p.policy_id for p in editor._custom_policies]
    assert custom_id not in remaining_ids


def test_delete_removes_from_qsettings(editor, settings, qtbot):
    """After delete, the custom policy is not present in QSettings pps/custom_policies."""
    custom_id = _add_custom_to_widget(editor)
    _select_policy(editor, custom_id)

    with patch(
        "app.ui.advanced_policy_editor.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        editor._on_delete_custom()

    raw = settings.value("pps/custom_policies", "[]", type=str)
    saved = json.loads(raw)
    saved_ids = [d.get("policy_id") for d in saved]
    assert custom_id not in saved_ids


def test_delete_removes_from_runtime_registry(editor, settings, qtbot):
    """After delete, the custom policy is removed from the runtime _CUSTOM_POLICIES registry."""
    from app.infra.translators.prompt_policy import register_custom_policy

    source = PROMPT_POLICIES["sentence_ru"]
    custom = clone_policy_as_custom(source, task_instruction="runtime registry test")
    editor._custom_policies.append(custom)
    editor._save_custom_policies_to_settings()
    editor._populate_policy_combo()
    # Also register in runtime registry to simulate active session
    register_custom_policy(custom)
    assert custom.policy_id in list_custom_policy_ids()

    _select_policy(editor, custom.policy_id)
    with patch(
        "app.ui.advanced_policy_editor.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        editor._on_delete_custom()

    assert custom.policy_id not in list_custom_policy_ids()


# ---------------------------------------------------------------------------
# Fallback behaviour when active policy is deleted
# ---------------------------------------------------------------------------


def test_delete_active_policy_switches_dropdown_to_builtin(editor, qtbot):
    """After deleting the selected custom policy, the dropdown selects a built-in."""
    custom_id = _add_custom_to_widget(editor)
    _select_policy(editor, custom_id)

    with patch(
        "app.ui.advanced_policy_editor.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        editor._on_delete_custom()

    # After delete, current selection must be a built-in (not the deleted custom)
    current_id = editor._policy_combo.currentData()
    assert current_id in PROMPT_POLICIES
    assert current_id != custom_id


def test_delete_active_policy_base_policy_is_builtin(editor, qtbot):
    """After deleting the selected custom policy, _base_policy is a built-in PromptPolicy."""
    custom_id = _add_custom_to_widget(editor)
    _select_policy(editor, custom_id)

    with patch(
        "app.ui.advanced_policy_editor.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        editor._on_delete_custom()

    assert editor._base_policy is not None
    assert editor._base_policy.policy_id in PROMPT_POLICIES


def test_delete_last_custom_policy_leaves_valid_state(editor, qtbot):
    """Deleting the only custom policy leaves the editor working with a built-in selected."""
    custom_id = _add_custom_to_widget(editor)
    assert len(editor._custom_policies) == 1
    _select_policy(editor, custom_id)

    with patch(
        "app.ui.advanced_policy_editor.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        editor._on_delete_custom()

    # No custom policies left
    assert editor._custom_policies == []
    # Dropdown still has built-ins
    assert editor._policy_combo.count() == len(PROMPT_POLICIES)
    # Delete button must be disabled (built-in selected)
    assert not editor._delete_btn.isEnabled()


# ---------------------------------------------------------------------------
# Cancellation: confirm dialog cancelled → no changes
# ---------------------------------------------------------------------------


def test_cancel_delete_leaves_everything_intact(editor, qtbot, settings):
    """Cancelling the confirm dialog does not remove the custom policy."""
    custom_id = _add_custom_to_widget(editor)
    _select_policy(editor, custom_id)

    with patch(
        "app.ui.advanced_policy_editor.QMessageBox.question",
        return_value=QMessageBox.StandardButton.No,
    ):
        editor._on_delete_custom()

    # Still in dropdown
    assert editor._policy_combo.findData(custom_id) >= 0
    # Still in in-memory list
    remaining_ids = [p.policy_id for p in editor._custom_policies]
    assert custom_id in remaining_ids
    # Still in QSettings
    raw = settings.value("pps/custom_policies", "[]", type=str)
    saved_ids = [d.get("policy_id") for d in json.loads(raw)]
    assert custom_id in saved_ids
