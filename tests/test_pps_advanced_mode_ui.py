"""PPS PATCH-10 — Advanced Mode UI tests.

Tests for:
- Policy Editor tab present in ProviderSettingsDialog
- Policy dropdown: full registry including experimental profiles
- Policy dropdown label format: "{name} [{policy_id}]"
- allow_user_edit_* correctly enables/disables text editors
- Reset restores the built-in base value
- Save as Custom creates independent copy (is_custom=True, new policy_id)
- Editing custom policy does NOT mutate the built-in source
- Custom policy persists after widget reload
- Invalid persisted custom policy JSON fails safely (no crash)
- Sampling and mode selectors load correct values from policy
- Export YAML produces valid expected content
- Advanced Mode active/inactive → load_pps_request_options behaviour
- PATCH-09b wiring: load_pps_request_options uses advanced options when active
- Basic Mode UI unaffected by Advanced Mode
"""

import json
import os
import tempfile

import pytest
from PyQt6.QtCore import QSettings

from app.infra.translators.prompt_policy import PROMPT_POLICIES, TerminologyMode
from app.ui.advanced_policy_editor import (
    AdvancedPolicyEditorWidget,
    _serialise_for_export,
    clone_policy_as_custom,
    dict_to_policy,
    policy_to_dict,
)
from app.ui.provider_settings_dialog import ProviderSettingsDialog, load_pps_request_options


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_test_settings(name: str = "AdvancedPolicyEditor") -> QSettings:
    s = QSettings(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        "HDLE_Test",
        name,
    )
    return s


@pytest.fixture
def settings():
    s = _make_test_settings()
    s.clear()
    s.sync()
    yield s
    s.clear()
    s.sync()


@pytest.fixture
def editor(qtbot, settings):
    w = AdvancedPolicyEditorWidget(settings=settings)
    qtbot.addWidget(w)
    yield w


@pytest.fixture
def dialog(qtbot):
    s = _make_test_settings("DialogTest")
    s.clear()
    s.sync()
    d = ProviderSettingsDialog(settings=s)
    qtbot.addWidget(d)
    yield d
    s.clear()
    s.sync()


# ---------------------------------------------------------------------------
# Tab presence
# ---------------------------------------------------------------------------


def test_policy_editor_tab_present(dialog):
    """'Policy Editor' tab must exist in the dialog."""
    titles = [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())]
    assert "Policy Editor" in titles


def test_basic_mode_tab_still_present(dialog):
    """'Prompt Policy' (Basic Mode) tab must still coexist with Policy Editor."""
    titles = [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())]
    assert "Prompt Policy" in titles


# ---------------------------------------------------------------------------
# Policy dropdown content
# ---------------------------------------------------------------------------


def _combo_policy_ids(editor: AdvancedPolicyEditorWidget) -> list[str]:
    return [editor._policy_combo.itemData(i) for i in range(editor._policy_combo.count())]


def test_policy_dropdown_includes_all_builtin(editor):
    """All 6 built-in policy IDs must appear in the dropdown."""
    ids = _combo_policy_ids(editor)
    for pid in PROMPT_POLICIES:
        assert pid in ids, f"Missing policy_id {pid!r} in dropdown"


def test_policy_dropdown_includes_experimental(editor):
    """sentence_ru_context (experimental=True) must appear in the dropdown."""
    assert "sentence_ru_context" in _combo_policy_ids(editor)


def test_policy_dropdown_label_format(editor):
    """Label format must be '{name} [{policy_id}]'."""
    for i in range(editor._policy_combo.count()):
        label = editor._policy_combo.itemText(i)
        pid = editor._policy_combo.itemData(i)
        if pid in PROMPT_POLICIES:
            assert f"[{pid}]" in label, f"Label {label!r} missing [{pid}]"


# ---------------------------------------------------------------------------
# allow_user_edit_* guard
# ---------------------------------------------------------------------------


def _select_policy(editor: AdvancedPolicyEditorWidget, policy_id: str) -> None:
    idx = editor._policy_combo.findData(policy_id)
    assert idx >= 0, f"policy_id {policy_id!r} not in dropdown"
    editor._policy_combo.setCurrentIndex(idx)


def test_allow_user_edit_role_false_disables_editor(editor):
    """sentence_ru.allow_user_edit_role=False → role editor must be read-only."""
    _select_policy(editor, "sentence_ru")
    assert editor._role_edit.isReadOnly() is True


def test_allow_user_edit_task_false_disables_editor(editor):
    """sentence_ru.allow_user_edit_task=False → task editor must be read-only."""
    _select_policy(editor, "sentence_ru")
    assert editor._task_edit.isReadOnly() is True


def test_allow_user_edit_task_true_enables_editor(editor):
    """sentence_ru_context.allow_user_edit_task=True → task editor must be editable."""
    _select_policy(editor, "sentence_ru_context")
    assert editor._task_edit.isReadOnly() is False


def test_allow_user_edit_output_false_disables_editor(editor):
    """sentence_ru.allow_user_edit_output_policy=False → output editor read-only."""
    _select_policy(editor, "sentence_ru")
    assert editor._output_edit.isReadOnly() is True


def test_reset_role_button_disabled_when_not_editable(editor):
    """Reset role button must be disabled for policies where allow_user_edit_role=False."""
    _select_policy(editor, "sentence_ru")
    assert editor._reset_role_btn.isEnabled() is False


def test_reset_task_button_enabled_when_editable(editor):
    """Reset task button must be enabled for sentence_ru_context."""
    _select_policy(editor, "sentence_ru_context")
    assert editor._reset_task_btn.isEnabled() is True


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


def test_reset_task_restores_builtin_value(editor):
    """Editing task then clicking Reset must restore the built-in value."""
    _select_policy(editor, "sentence_ru_context")
    original = PROMPT_POLICIES["sentence_ru_context"].task_instruction

    # Modify editor content
    editor._task_edit.setPlainText("MODIFIED CONTENT")
    assert editor._task_edit.toPlainText() == "MODIFIED CONTENT"

    # Reset
    editor._on_reset_task()
    assert editor._task_edit.toPlainText() == original


def test_reset_does_not_affect_readonly_editors(editor):
    """Reset on a disabled editor (sentence_ru role) must not change content."""
    _select_policy(editor, "sentence_ru")
    editor._on_reset_role()  # no-op; editor is read-only
    # Still correct built-in value
    assert editor._role_edit.toPlainText() == PROMPT_POLICIES["sentence_ru"].role_instruction


# ---------------------------------------------------------------------------
# Mode selectors
# ---------------------------------------------------------------------------


def test_terminology_selector_loaded_from_policy(editor):
    """Terminology combo must reflect the selected policy's terminology_mode."""
    _select_policy(editor, "sentence_ru")
    expected = str(PROMPT_POLICIES["sentence_ru"].terminology_mode)
    assert editor._terminology_combo.currentData() == expected


def test_sampling_selector_loaded_from_policy(editor):
    """Sampling combo must reflect the selected policy's sampling_profile_id."""
    _select_policy(editor, "lemma_ru")
    expected = PROMPT_POLICIES["lemma_ru"].sampling_profile_id
    assert editor._sampling_combo.currentData() == expected


def test_context_selector_loaded_from_sentence_ru_context(editor):
    """Context combo must reflect sentence_ru_context.context_mode."""
    _select_policy(editor, "sentence_ru_context")
    expected = str(PROMPT_POLICIES["sentence_ru_context"].context_mode)
    assert editor._context_combo.currentData() == expected


# ---------------------------------------------------------------------------
# Save as Custom
# ---------------------------------------------------------------------------


def test_save_as_custom_creates_independent_copy(editor, monkeypatch):
    """Save as Custom must create a policy that is not the same object as built-in."""
    monkeypatch.setattr(
        "app.ui.advanced_policy_editor.QMessageBox.information", lambda *a, **k: None
    )
    _select_policy(editor, "sentence_ru")

    editor._on_save_as_custom()

    assert len(editor._custom_policies) == 1
    assert editor._custom_policies[0] is not PROMPT_POLICIES["sentence_ru"]


def test_save_as_custom_sets_is_custom_true(editor, monkeypatch):
    """Save as Custom must produce a policy with is_custom=True."""
    monkeypatch.setattr(
        "app.ui.advanced_policy_editor.QMessageBox.information", lambda *a, **k: None
    )
    _select_policy(editor, "sentence_ru")
    editor._on_save_as_custom()

    assert editor._custom_policies[0].is_custom is True


def test_save_as_custom_sets_is_builtin_false(editor, monkeypatch):
    """Save as Custom must produce a policy with is_builtin=False."""
    monkeypatch.setattr(
        "app.ui.advanced_policy_editor.QMessageBox.information", lambda *a, **k: None
    )
    _select_policy(editor, "sentence_ru")
    editor._on_save_as_custom()

    assert editor._custom_policies[0].is_builtin is False


def test_save_as_custom_does_not_mutate_builtin(editor, monkeypatch):
    """Saving a custom copy must not change the built-in source policy."""
    monkeypatch.setattr(
        "app.ui.advanced_policy_editor.QMessageBox.information", lambda *a, **k: None
    )
    original_task = PROMPT_POLICIES["sentence_ru"].task_instruction

    _select_policy(editor, "sentence_ru_context")
    # Modify task (sentence_ru_context allows it)
    editor._task_edit.setPlainText("CUSTOM TASK TEXT")
    editor._on_save_as_custom()

    # sentence_ru built-in must be unchanged
    assert PROMPT_POLICIES["sentence_ru"].task_instruction == original_task


def test_save_as_custom_policy_id_format(editor, monkeypatch):
    """Custom policy_id must follow '{parent_id}_custom_{uuid8}' format."""
    monkeypatch.setattr(
        "app.ui.advanced_policy_editor.QMessageBox.information", lambda *a, **k: None
    )
    _select_policy(editor, "sentence_ru")
    editor._on_save_as_custom()

    custom_id = editor._custom_policies[0].policy_id
    assert custom_id.startswith("sentence_ru_custom_")
    suffix = custom_id[len("sentence_ru_custom_") :]
    assert len(suffix) == 8
    assert suffix.isalnum()


def test_save_as_custom_appears_in_dropdown(editor, monkeypatch):
    """After Save as Custom, new policy must appear in the dropdown."""
    monkeypatch.setattr(
        "app.ui.advanced_policy_editor.QMessageBox.information", lambda *a, **k: None
    )
    _select_policy(editor, "sentence_ru")
    editor._on_save_as_custom()

    custom_id = editor._custom_policies[0].policy_id
    ids = _combo_policy_ids(editor)
    assert custom_id in ids


# ---------------------------------------------------------------------------
# Custom policy persistence
# ---------------------------------------------------------------------------


def test_custom_policy_persists_after_reload(qtbot, settings, monkeypatch):
    """Custom policy saved to QSettings must survive widget reconstruction."""
    monkeypatch.setattr(
        "app.ui.advanced_policy_editor.QMessageBox.information", lambda *a, **k: None
    )

    editor1 = AdvancedPolicyEditorWidget(settings=settings)
    qtbot.addWidget(editor1)
    _select_policy(editor1, "sentence_ru")
    editor1._on_save_as_custom()
    custom_id = editor1._custom_policies[0].policy_id
    # Explicit save
    editor1._save_custom_policies_to_settings()

    # Recreate widget with same settings
    editor2 = AdvancedPolicyEditorWidget(settings=settings)
    qtbot.addWidget(editor2)

    loaded_ids = [p.policy_id for p in editor2._custom_policies]
    assert custom_id in loaded_ids


def test_invalid_custom_policy_json_fails_safely(qtbot):
    """Corrupt JSON in pps/custom_policies must not crash widget construction."""
    s = _make_test_settings("CorruptTest")
    s.clear()
    s.setValue("pps/custom_policies", "NOT VALID JSON {{{")
    s.sync()

    # Must not raise
    editor = AdvancedPolicyEditorWidget(settings=s)
    qtbot.addWidget(editor)
    assert editor._custom_policies == []

    s.clear()
    s.sync()


def test_custom_policy_with_missing_required_field_skipped(qtbot):
    """Custom policy dict missing required fields must be silently skipped."""
    s = _make_test_settings("MissingField")
    s.clear()
    # dict without 'name' required field
    s.setValue(
        "pps/custom_policies",
        json.dumps([{"policy_id": "broken_custom_abc12345"}]),  # missing 'name'
    )
    s.sync()

    editor = AdvancedPolicyEditorWidget(settings=s)
    qtbot.addWidget(editor)
    assert editor._custom_policies == []

    s.clear()
    s.sync()


# ---------------------------------------------------------------------------
# policy_to_dict / dict_to_policy
# ---------------------------------------------------------------------------


def test_policy_to_dict_round_trips(editor):
    """policy_to_dict → dict_to_policy must produce an equivalent policy."""
    source = PROMPT_POLICIES["sentence_ru"]
    d = policy_to_dict(source)
    restored = dict_to_policy(d)
    assert restored is not None
    assert restored.policy_id == source.policy_id
    assert restored.task_instruction == source.task_instruction
    assert restored.terminology_mode == source.terminology_mode


def test_clone_policy_as_custom_independent(editor):
    """clone_policy_as_custom must not share data with the source."""
    source = PROMPT_POLICIES["sentence_ru"]
    custom = clone_policy_as_custom(source)
    assert custom.policy_id != source.policy_id
    assert custom.is_custom is True
    assert custom.is_builtin is False


# ---------------------------------------------------------------------------
# Export YAML
# ---------------------------------------------------------------------------


def test_serialise_for_export_yaml(tmp_path):
    """_serialise_for_export must produce YAML for .yaml extension."""
    import yaml

    d = {"policy_id": "test", "name": "Test Policy", "task_instruction": "do this"}
    path = str(tmp_path / "test.yaml")
    text = _serialise_for_export(d, path)
    # Must parse as valid YAML
    parsed = yaml.safe_load(text)
    assert parsed["policy_id"] == "test"
    assert parsed["name"] == "Test Policy"


def test_serialise_for_export_json_fallback(tmp_path):
    """_serialise_for_export must produce valid JSON for .json extension."""
    d = {"policy_id": "test", "name": "Test"}
    path = str(tmp_path / "test.json")
    text = _serialise_for_export(d, path)
    parsed = json.loads(text)
    assert parsed["policy_id"] == "test"


def test_export_creates_file(editor, monkeypatch, tmp_path):
    """_on_export must write a file with expected content."""
    export_path = str(tmp_path / "policy_export.yaml")

    # Patch QFileDialog to return our path without showing UI
    monkeypatch.setattr(
        "app.ui.advanced_policy_editor.QFileDialog.getSaveFileName",
        lambda *a, **k: (export_path, ""),
    )
    monkeypatch.setattr(
        "app.ui.advanced_policy_editor.QMessageBox.information", lambda *a, **k: None
    )

    _select_policy(editor, "sentence_ru")
    editor._on_export()

    assert os.path.exists(export_path)
    content = open(export_path, encoding="utf-8").read()
    assert "sentence_ru" in content


# ---------------------------------------------------------------------------
# load_pps_request_options — Advanced Mode integration
# ---------------------------------------------------------------------------


def test_advanced_mode_inactive_returns_basic_options():
    """load_pps_request_options must return basic options when advanced is off."""
    s = _make_test_settings("ReqOptsBasic")
    s.clear()
    s.setValue("pps/advanced/active", False)
    s.setValue("pps/basic/policy_id", "lemma_ru")
    s.setValue("pps/basic/use_glossary", False)
    s.sync()

    opts = load_pps_request_options(settings=s)
    assert opts["prompt_policy_id"] == "lemma_ru"
    assert opts["use_glossary"] is False

    s.clear()
    s.sync()


def test_advanced_mode_active_returns_advanced_options():
    """load_pps_request_options must return advanced options when active."""
    s = _make_test_settings("ReqOptsAdv")
    s.clear()
    s.setValue("pps/advanced/active", True)
    s.setValue("pps/advanced/policy_id", "term_ru")
    s.setValue("pps/advanced/terminology_mode", "off")
    s.setValue("pps/advanced/sampling_profile_id", "hy_mt_precise_short")
    s.sync()

    opts = load_pps_request_options(settings=s)
    assert opts["prompt_policy_id"] == "term_ru"
    assert opts["use_glossary"] is False  # terminology_mode="off"
    assert opts["sampling_profile_id"] == "hy_mt_precise_short"

    s.clear()
    s.sync()


def test_advanced_mode_overrides_basic_policy():
    """When advanced active, advanced policy_id wins over basic policy_id."""
    s = _make_test_settings("ReqOptsOverride")
    s.clear()
    s.setValue("pps/basic/policy_id", "sentence_ru")
    s.setValue("pps/advanced/active", True)
    s.setValue("pps/advanced/policy_id", "lemma_ru")
    s.sync()

    opts = load_pps_request_options(settings=s)
    assert opts["prompt_policy_id"] == "lemma_ru"  # advanced wins

    s.clear()
    s.sync()


def test_advanced_mode_terminology_off_use_glossary_false():
    """Advanced mode with terminology_mode=off must produce use_glossary=False."""
    s = _make_test_settings("TermOff")
    s.clear()
    s.setValue("pps/advanced/active", True)
    s.setValue("pps/advanced/terminology_mode", str(TerminologyMode.OFF))
    s.sync()

    opts = load_pps_request_options(settings=s)
    assert opts["use_glossary"] is False

    s.clear()
    s.sync()


def test_advanced_mode_terminology_soft_use_glossary_true():
    """Advanced mode with soft_glossary must produce use_glossary=True."""
    s = _make_test_settings("TermSoft")
    s.clear()
    s.setValue("pps/advanced/active", True)
    s.setValue("pps/advanced/terminology_mode", str(TerminologyMode.SOFT_GLOSSARY))
    s.sync()

    opts = load_pps_request_options(settings=s)
    assert opts["use_glossary"] is True

    s.clear()
    s.sync()


# ---------------------------------------------------------------------------
# get_advanced_options() widget method
# ---------------------------------------------------------------------------


def test_get_advanced_options_empty_when_inactive(editor):
    """get_advanced_options() must return {} when Use Advanced Mode unchecked."""
    editor._active_cb.setChecked(False)
    assert editor.get_advanced_options() == {}


def test_get_advanced_options_has_policy_id_when_active(editor):
    """get_advanced_options() must include prompt_policy_id when active."""
    editor._active_cb.setChecked(True)
    opts = editor.get_advanced_options()
    assert "prompt_policy_id" in opts
    assert opts["prompt_policy_id"]  # non-empty


def test_get_advanced_options_is_active_false_by_default(editor):
    """Advanced Mode must be off by default."""
    assert editor.is_advanced_active() is False


# ---------------------------------------------------------------------------
# load_settings / save_settings round-trip
# ---------------------------------------------------------------------------


def test_save_then_load_advanced_state(qtbot, settings):
    """save_settings → load_settings on fresh widget must restore state."""
    editor1 = AdvancedPolicyEditorWidget(settings=settings)
    qtbot.addWidget(editor1)

    editor1._active_cb.setChecked(True)
    idx = editor1._policy_combo.findData("lemma_ru")
    editor1._policy_combo.setCurrentIndex(idx)
    editor1.save_settings()

    editor2 = AdvancedPolicyEditorWidget(settings=settings)
    qtbot.addWidget(editor2)
    editor2.load_settings()

    assert editor2._active_cb.isChecked() is True
    assert editor2._policy_combo.currentData() == "lemma_ru"
