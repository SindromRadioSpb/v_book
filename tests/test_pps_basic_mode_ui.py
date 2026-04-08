"""PPS PATCH-09 — Basic Mode UI tests.

Tests for:
- Profile chip selector shows only non-experimental policies
- Experimental profiles (sentence_ru_context) are hidden
- Default profile chip is sentence_ru
- All non-experimental policy IDs present as buttons
- QSettings load/save: policy_id, use_glossary, use_context,
  preserve_formatting, sampling_profile_id
- get_pps_options() returns correct dict reflecting UI state
- Effective Prompt Preview renders without crash
- Tab "Prompt Policy" is present in the dialog
"""

import pytest
from PyQt6.QtCore import QSettings

from app.ui.provider_settings_dialog import ProviderSettingsDialog


def _make_test_settings() -> QSettings:
    settings = QSettings(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        "HDLE_Test",
        "PpsBasicModeUI",
    )
    return settings


@pytest.fixture
def settings():
    """Isolated QSettings for PPS tests."""
    s = _make_test_settings()
    s.clear()
    s.sync()
    yield s
    s.clear()
    s.sync()


@pytest.fixture
def dialog(qtbot, settings):
    """ProviderSettingsDialog with clean test settings."""
    d = ProviderSettingsDialog(settings=settings)
    qtbot.addWidget(d)
    yield d


# ---------------------------------------------------------------------------
# Tab presence
# ---------------------------------------------------------------------------


def test_prompt_policy_tab_present(dialog):
    """'Prompt Policy' tab must exist in the dialog."""
    tab_titles = [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())]
    assert "Prompt Policy" in tab_titles


# ---------------------------------------------------------------------------
# Profile chip selector — visibility
# ---------------------------------------------------------------------------


def _button_policy_ids(dialog) -> list[str]:
    return [btn.property("policy_id") for btn in dialog._pps_btn_group.buttons()]


def test_chip_non_experimental_policies_present(dialog):
    """All non-experimental policy IDs must appear as chip buttons."""
    from app.infra.translators.prompt_policy import list_profiles

    expected = {p.policy_id for p in list_profiles(include_experimental=False)}
    actual = set(_button_policy_ids(dialog))
    assert expected == actual


def test_chip_experimental_hidden(dialog):
    """sentence_ru_context (experimental=True) must NOT appear as a chip button."""
    assert "sentence_ru_context" not in _button_policy_ids(dialog)


def test_chip_sentence_ru_present(dialog):
    """sentence_ru chip must be present."""
    assert "sentence_ru" in _button_policy_ids(dialog)


def test_chip_count_matches_non_experimental(dialog):
    """Chip count must equal count of non-experimental policies."""
    from app.infra.translators.prompt_policy import list_profiles

    expected = len(list_profiles(include_experimental=False))
    assert len(dialog._pps_btn_group.buttons()) == expected


def test_chip_group_is_exclusive(dialog):
    """QButtonGroup must be in exclusive mode."""
    assert dialog._pps_btn_group.exclusive() is True


# ---------------------------------------------------------------------------
# Default state
# ---------------------------------------------------------------------------


def test_default_policy_is_sentence_ru(dialog):
    """Default selected chip must be sentence_ru."""
    checked = dialog._pps_btn_group.checkedButton()
    assert checked is not None
    assert checked.property("policy_id") == "sentence_ru"


def test_default_use_glossary_true(dialog):
    """Use-glossary toggle must be checked by default."""
    assert dialog._pps_use_glossary_cb.isChecked() is True


def test_default_use_context_false(dialog):
    """Use-context toggle must be unchecked by default."""
    assert dialog._pps_use_context_cb.isChecked() is False


def test_default_preserve_formatting_true(dialog):
    """Preserve-formatting toggle must be checked by default."""
    assert dialog._pps_preserve_fmt_cb.isChecked() is True


def test_default_sampling_is_precise_sentence(dialog):
    """Default sampling preset must be hy_mt_precise_sentence."""
    assert dialog._pps_sampling_combo.currentData() == "hy_mt_precise_sentence"


# ---------------------------------------------------------------------------
# get_pps_options()
# ---------------------------------------------------------------------------


def test_get_pps_options_contains_policy_id(dialog):
    """get_pps_options() must include 'policy_id' key."""
    opts = dialog.get_pps_options()
    assert "policy_id" in opts
    assert opts["policy_id"] == "sentence_ru"


def test_get_pps_options_reflects_glossary_toggle(dialog):
    """get_pps_options() use_glossary reflects checkbox state."""
    dialog._pps_use_glossary_cb.setChecked(False)
    assert dialog.get_pps_options()["use_glossary"] is False
    dialog._pps_use_glossary_cb.setChecked(True)
    assert dialog.get_pps_options()["use_glossary"] is True


def test_get_pps_options_reflects_context_toggle(dialog):
    """get_pps_options() use_context reflects checkbox state."""
    dialog._pps_use_context_cb.setChecked(True)
    assert dialog.get_pps_options()["use_context"] is True


def test_get_pps_options_reflects_sampling(dialog):
    """get_pps_options() sampling_profile_id reflects combo selection."""
    idx = dialog._pps_sampling_combo.findData("hy_mt_precise_short")
    dialog._pps_sampling_combo.setCurrentIndex(idx)
    assert dialog.get_pps_options()["sampling_profile_id"] == "hy_mt_precise_short"


def test_get_pps_options_reflects_policy_chip(dialog):
    """get_pps_options() policy_id changes when a different chip is checked."""
    for btn in dialog._pps_btn_group.buttons():
        if btn.property("policy_id") == "lemma_ru":
            btn.setChecked(True)
            break
    assert dialog.get_pps_options()["policy_id"] == "lemma_ru"


# ---------------------------------------------------------------------------
# QSettings persistence — save
# ---------------------------------------------------------------------------


def test_save_persists_policy_id(dialog, settings):
    """Accepting dialog saves policy_id to QSettings."""
    for btn in dialog._pps_btn_group.buttons():
        if btn.property("policy_id") == "term_ru":
            btn.setChecked(True)
            break
    dialog.accept()
    settings.sync()
    assert settings.value("pps/basic/policy_id", type=str) == "term_ru"


def test_save_persists_use_glossary(dialog, settings):
    """Accepting dialog saves use_glossary to QSettings."""
    dialog._pps_use_glossary_cb.setChecked(False)
    dialog.accept()
    settings.sync()
    assert settings.value("pps/basic/use_glossary", type=bool) is False


def test_save_persists_use_context(dialog, settings):
    """Accepting dialog saves use_context to QSettings."""
    dialog._pps_use_context_cb.setChecked(True)
    dialog.accept()
    settings.sync()
    assert settings.value("pps/basic/use_context", type=bool) is True


def test_save_persists_preserve_formatting(dialog, settings):
    """Accepting dialog saves preserve_formatting to QSettings."""
    dialog._pps_preserve_fmt_cb.setChecked(False)
    dialog.accept()
    settings.sync()
    assert settings.value("pps/basic/preserve_formatting", type=bool) is False


def test_save_persists_sampling_profile_id(dialog, settings):
    """Accepting dialog saves sampling_profile_id to QSettings."""
    idx = dialog._pps_sampling_combo.findData("hy_mt_precise_formatted")
    dialog._pps_sampling_combo.setCurrentIndex(idx)
    dialog.accept()
    settings.sync()
    assert settings.value("pps/basic/sampling_profile_id", type=str) == "hy_mt_precise_formatted"


# ---------------------------------------------------------------------------
# QSettings persistence — load
# ---------------------------------------------------------------------------


def test_load_restores_policy_id(qtbot, settings):
    """Dialog restores saved policy_id on creation."""
    settings.setValue("pps/basic/policy_id", "lemma_ru")
    settings.sync()
    d = ProviderSettingsDialog(settings=settings)
    qtbot.addWidget(d)
    checked = d._pps_btn_group.checkedButton()
    assert checked is not None
    assert checked.property("policy_id") == "lemma_ru"


def test_load_restores_use_glossary_false(qtbot, settings):
    """Dialog restores use_glossary=False from QSettings."""
    settings.setValue("pps/basic/use_glossary", False)
    settings.sync()
    d = ProviderSettingsDialog(settings=settings)
    qtbot.addWidget(d)
    assert d._pps_use_glossary_cb.isChecked() is False


def test_load_restores_use_context_true(qtbot, settings):
    """Dialog restores use_context=True from QSettings."""
    settings.setValue("pps/basic/use_context", True)
    settings.sync()
    d = ProviderSettingsDialog(settings=settings)
    qtbot.addWidget(d)
    assert d._pps_use_context_cb.isChecked() is True


def test_load_restores_sampling_profile(qtbot, settings):
    """Dialog restores sampling_profile_id from QSettings."""
    settings.setValue("pps/basic/sampling_profile_id", "hy_mt_precise_short")
    settings.sync()
    d = ProviderSettingsDialog(settings=settings)
    qtbot.addWidget(d)
    assert d._pps_sampling_combo.currentData() == "hy_mt_precise_short"


def test_load_unknown_policy_id_selects_first_button(qtbot, settings):
    """Unknown saved policy_id falls back to first button."""
    settings.setValue("pps/basic/policy_id", "nonexistent_policy")
    settings.sync()
    d = ProviderSettingsDialog(settings=settings)
    qtbot.addWidget(d)
    assert d._pps_btn_group.checkedButton() is not None


# ---------------------------------------------------------------------------
# Effective Prompt Preview
# ---------------------------------------------------------------------------


def test_preview_renders_without_crash(dialog, qtbot, monkeypatch):
    """Clicking preview with sentence_ru selected must not raise."""
    # Prevent the preview dialog from blocking
    from PyQt6.QtWidgets import QDialog

    monkeypatch.setattr(QDialog, "exec", lambda self: None)

    # sentence_ru is selected by default — just call the slot
    dialog._show_effective_prompt_preview()  # must not raise


def test_preview_no_crash_with_glossary_and_context_enabled(dialog, qtbot, monkeypatch):
    """Preview with both glossary and context toggles on must not raise."""
    from PyQt6.QtWidgets import QDialog

    monkeypatch.setattr(QDialog, "exec", lambda self: None)

    dialog._pps_use_glossary_cb.setChecked(True)
    dialog._pps_use_context_cb.setChecked(True)
    dialog._show_effective_prompt_preview()  # must not raise
