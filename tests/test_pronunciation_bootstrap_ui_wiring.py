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

def test_dialog_sanitizes_model_path_before_persist(qtbot):
    SettingsService.reset_instance()
    settings = SettingsService.get_instance()
    settings._settings.clear()
    settings.sync()

    dialog = PronunciationBootstrapDialog()
    qtbot.addWidget(dialog)
    dialog.model_path_edit.setText(' "J:/Models/phonikud/phonikud-1.0.int8." ')
    dialog._save_settings()

    assert dialog.model_path_edit.text() == "J:/Models/phonikud/phonikud-1.0.int8"
    assert settings.get_string("pronunciation/phonikud/model_path", "") == "J:/Models/phonikud/phonikud-1.0.int8"


def test_dialog_accepts_selected_items_scope(qtbot):
    dialog = PronunciationBootstrapDialog(
        selected_items=[
            {
                "src_lang": "he",
                "src_text": "שלום",
                "src_norm": "שלום",
                "source_group": "lemmas",
            },
            {
                "src_lang": "he",
                "src_text": "מישור משופע",
                "src_norm": "מישור_משופע",
                "source_group": "terms",
            },
        ]
    )
    qtbot.addWidget(dialog)
    assert len(dialog.selected_items) == 2
    assert dialog.selected_items[0]["source_group"] == "lemmas"
    assert dialog.selected_items[1]["source_group"] == "terms"
    assert dialog.include_lemmas_cb.isChecked() is True
    assert dialog.include_terms_cb.isChecked() is True
    assert dialog.include_ud_cb.isChecked() is False
