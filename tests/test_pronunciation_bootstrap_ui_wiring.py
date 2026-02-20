"""UI wiring tests for pronunciation bootstrap dialog."""

from __future__ import annotations

from app.infra.settings import SettingsService
from app.ui.dialogs.pronunciation_bootstrap_dialog import PronunciationBootstrapDialog


def test_dialog_persists_model_path_and_enabled_flag(qtbot):
    SettingsService.reset_instance()
    settings = SettingsService.get_instance()
    settings._settings.clear()
    settings.sync()

    dialog = PronunciationBootstrapDialog()
    qtbot.addWidget(dialog)
    dialog.model_path_edit.setText("J:/models/phonikud")
    dialog.enabled_checkbox.setChecked(False)
    dialog._save_settings()

    dialog2 = PronunciationBootstrapDialog()
    qtbot.addWidget(dialog2)
    assert dialog2.model_path_edit.text() == "J:/models/phonikud"
    assert dialog2.enabled_checkbox.isChecked() is False


def test_dialog_renders_health_status_and_samples(qtbot):
    dialog = PronunciationBootstrapDialog()
    qtbot.addWidget(dialog)

    dialog._render_health(
        {
            "mode": "real_inference",
            "status": "ok",
            "details": "Real inference active",
            "latency_ms": 12,
            "samples": [{"input": "שלום", "output": "שָׁלוֹם"}],
        }
    )

    assert "real_inference" in dialog.health_mode_label.text()
    assert "latency=12ms" in dialog.health_details_label.text()
    assert "שלום -> שָׁלוֹם" in dialog.health_samples_label.text()
