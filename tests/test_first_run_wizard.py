"""Tests for first-run wizard resource visibility and skip behavior."""

from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog

from app.infra.settings import SettingsService
from app.ui.first_run_wizard import FirstRunWizardDialog


def _disable_background_health(monkeypatch) -> None:
    monkeypatch.setattr(FirstRunWizardDialog, "_refresh_health_summary", lambda self: None)


def _write_manifest(path: Path) -> None:
    payload = {
        "manifest_version": "1.0",
        "resources": [
            {
                "id": "nikud_pronunciation_model",
                "display_name": "Phonikud Pronunciation Model",
                "version": "1.0",
                "type": "model",
                "required": True,
                "payload_kind": "manual_import",
                "download_url": "",
                "size_bytes": 123,
                "checksum": "",
                "local_install_subdir": "models/phonikud",
                "filenames": ["phonikud-1.0.int8.onnx"],
                "description": "test",
            },
            {
                "id": "sentence_niqqud_model",
                "display_name": "Sentence Niqqud Model",
                "version": "1.0",
                "type": "model",
                "required": True,
                "payload_kind": "manual_import",
                "download_url": "",
                "size_bytes": 123,
                "checksum": "",
                "local_install_subdir": "models/phonikud",
                "filenames": ["phonikud-1.0.int8.onnx"],
                "description": "test",
            },
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_first_run_wizard_shows_missing_models_and_can_skip(monkeypatch, qtbot, tmp_path):
    SettingsService.reset_instance()
    settings = SettingsService.get_instance()
    settings._settings.clear()
    settings.sync()
    _disable_background_health(monkeypatch)

    manifest_path = tmp_path / "resource_manifest.json"
    _write_manifest(manifest_path)
    settings.set_value("resources/manifest_path", str(manifest_path))
    settings.set_value("resources/data_root", str(tmp_path / "hdle_data"))
    settings.set_value("setup/first_run_completed", False)
    settings.sync()

    dialog = FirstRunWizardDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.wait(50)
    dialog._refresh_resource_status()

    models_text = dialog.models_status_label.text().lower()
    assert "missing" in models_text

    qtbot.mouseClick(dialog.skip_btn, Qt.MouseButton.LeftButton)
    assert dialog.result() == int(QDialog.DialogCode.Rejected)
