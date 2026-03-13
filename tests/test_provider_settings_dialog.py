"""Tests for Provider Settings Dialog.

Tests verify:
- Dialog creation and initialization
- Settings load/save
- Rate limit configuration
- Provider enable/disable
- Chain reordering
- Restore defaults
"""
import pytest
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import QDialogButtonBox

from app.ui.provider_settings_dialog import ProviderSettingsDialog


def _make_test_settings() -> QSettings:
    settings = QSettings(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        "HDLE_Test",
        "ProviderSettings",
    )
    return settings


@pytest.fixture
def settings(qtbot):
    """Create temporary QSettings for testing."""
    settings = _make_test_settings()
    settings.clear()
    settings.sync()
    yield settings
    settings.clear()
    settings.sync()


@pytest.fixture
def dialog(qtbot):
    """Create ProviderSettingsDialog for testing."""
    # Create test settings
    settings = _make_test_settings()
    settings.clear()
    settings.sync()

    # Pass settings to dialog
    dialog = ProviderSettingsDialog(settings=settings)
    qtbot.addWidget(dialog)
    yield dialog
    settings.clear()
    settings.sync()


# ============================================================================
# Test 1: Dialog initialization
# ============================================================================


def test_dialog_creation(dialog):
    """Dialog creates successfully with all providers."""
    assert dialog.windowTitle() == "MT Provider Settings"

    # Check all providers have widgets
    assert "deepl" in dialog.provider_widgets
    assert "microsoft" in dialog.provider_widgets
    assert "libretranslate" in dialog.provider_widgets
    assert "local_nllb" in dialog.provider_widgets
    assert "local_seamless" in dialog.provider_widgets


def test_dialog_default_values(dialog):
    """Dialog loads with default values."""
    # DeepL should be enabled by default
    deepl_widgets = dialog.provider_widgets["deepl"]
    assert deepl_widgets["enabled"].isChecked() is True
    assert deepl_widgets["rate_limit"].value() == 60

    # Local NLLB should be disabled by default
    local_nllb_widgets = dialog.provider_widgets["local_nllb"]
    assert local_nllb_widgets["enabled"].isChecked() is False
    assert local_nllb_widgets["rate_limit"].value() == 9999


# ============================================================================
# Test 2: Rate limit configuration
# ============================================================================


def test_rate_limit_range(dialog):
    """Rate limit spinbox has correct range."""
    for widgets in dialog.provider_widgets.values():
        rate_limit_spin = widgets["rate_limit"]
        assert rate_limit_spin.minimum() == 1
        assert rate_limit_spin.maximum() == 10000


def test_change_rate_limit(dialog, qtbot):
    """Changing rate limit updates widget."""
    deepl_widgets = dialog.provider_widgets["deepl"]
    rate_limit_spin = deepl_widgets["rate_limit"]

    rate_limit_spin.setValue(100)
    assert rate_limit_spin.value() == 100


# ============================================================================
# Test 3: Provider enable/disable
# ============================================================================


def test_enable_disable_provider(dialog, qtbot):
    """Enabling/disabling provider updates checkbox."""
    local_nllb_widgets = dialog.provider_widgets["local_nllb"]
    enabled_cb = local_nllb_widgets["enabled"]

    # Initially disabled
    assert enabled_cb.isChecked() is False

    # Enable
    enabled_cb.setChecked(True)
    assert enabled_cb.isChecked() is True

    # Disable
    enabled_cb.setChecked(False)
    assert enabled_cb.isChecked() is False


# ============================================================================
# Test 4: Save settings
# ============================================================================


def test_save_settings(dialog, qtbot):
    """Accepting dialog saves settings."""
    # Change settings
    deepl_widgets = dialog.provider_widgets["deepl"]
    deepl_widgets["rate_limit"].setValue(120)
    deepl_widgets["enabled"].setChecked(False)

    # Accept dialog
    dialog.accept()

    # Check settings saved
    settings = _make_test_settings()
    settings.sync()
    assert settings.value("mt/providers/deepl/rate_limit", type=int) == 120
    assert settings.value("mt/providers/deepl/enabled", type=bool) is False


def test_cancel_does_not_save(dialog, qtbot):
    """Rejecting dialog does not save settings."""
    # Set initial value
    settings = _make_test_settings()
    settings.setValue("mt/providers/deepl/rate_limit", 60)
    settings.sync()

    # Change value in dialog
    deepl_widgets = dialog.provider_widgets["deepl"]
    deepl_widgets["rate_limit"].setValue(120)

    # Reject dialog
    dialog.reject()

    # Check settings not changed
    settings.sync()
    assert settings.value("mt/providers/deepl/rate_limit", type=int) == 60


# ============================================================================
# Test 5: Chain reordering
# ============================================================================


def test_chain_list_populated(dialog):
    """Chain list contains all providers."""
    # 7 providers: google_translate, google_cloud_translate, deepl, microsoft,
    # libretranslate, local_nllb, local_seamless
    assert dialog.chain_list.count() == 7


def test_move_up(dialog, qtbot):
    """Moving provider up in chain works."""
    # Select second item
    dialog.chain_list.setCurrentRow(1)
    first_item_text = dialog.chain_list.item(0).text()

    # Move up
    dialog._move_up()

    # Check moved
    assert dialog.chain_list.currentRow() == 0
    assert dialog.chain_list.item(1).text() == first_item_text


def test_move_down(dialog, qtbot):
    """Moving provider down in chain works."""
    # Select first item
    dialog.chain_list.setCurrentRow(0)
    first_item_text = dialog.chain_list.item(0).text()

    # Move down
    dialog._move_down()

    # Check moved
    assert dialog.chain_list.currentRow() == 1
    assert dialog.chain_list.item(1).text() == first_item_text


def test_move_up_at_top_does_nothing(dialog, qtbot):
    """Moving first item up does nothing."""
    dialog.chain_list.setCurrentRow(0)
    first_item_text = dialog.chain_list.item(0).text()

    dialog._move_up()

    assert dialog.chain_list.currentRow() == 0
    assert dialog.chain_list.item(0).text() == first_item_text


def test_move_down_at_bottom_does_nothing(dialog, qtbot):
    """Moving last item down does nothing."""
    last_row = dialog.chain_list.count() - 1
    dialog.chain_list.setCurrentRow(last_row)
    last_item_text = dialog.chain_list.item(last_row).text()

    dialog._move_down()

    assert dialog.chain_list.currentRow() == last_row
    assert dialog.chain_list.item(last_row).text() == last_item_text


# ============================================================================
# Test 6: Restore defaults
# ============================================================================


def test_restore_defaults(dialog, qtbot, monkeypatch):
    """Restore defaults resets all settings."""
    # Change settings
    deepl_widgets = dialog.provider_widgets["deepl"]
    deepl_widgets["rate_limit"].setValue(120)
    deepl_widgets["enabled"].setChecked(False)

    # Mock message box to auto-accept
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    )

    # Restore defaults
    dialog._restore_defaults()

    # Check restored
    assert deepl_widgets["rate_limit"].value() == 60
    assert deepl_widgets["enabled"].isChecked() is True


def test_restore_defaults_cancelled(dialog, qtbot, monkeypatch):
    """Restore defaults can be cancelled."""
    # Change settings
    deepl_widgets = dialog.provider_widgets["deepl"]
    deepl_widgets["rate_limit"].setValue(120)

    # Mock message box to decline
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No
    )

    # Try to restore defaults
    dialog._restore_defaults()

    # Check not restored
    assert deepl_widgets["rate_limit"].value() == 120


# ============================================================================
# Test 7: Load saved settings
# ============================================================================


def test_load_saved_settings(qtbot):
    """Dialog loads previously saved settings."""
    # Save settings
    settings = _make_test_settings()
    settings.clear()
    settings.setValue("mt/providers/deepl/rate_limit", 150)
    settings.setValue("mt/providers/deepl/enabled", False)
    settings.sync()

    # Create new dialog with saved settings
    dialog = ProviderSettingsDialog(settings=settings)
    qtbot.addWidget(dialog)

    # Check loaded
    deepl_widgets = dialog.provider_widgets["deepl"]
    assert deepl_widgets["rate_limit"].value() == 150
    assert deepl_widgets["enabled"].isChecked() is False

    settings.clear()
    settings.sync()
