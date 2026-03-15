"""Tests for first-run wizard database selection step."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.infra.db_path_resolver import (
    SETTINGS_KEY_ACTIVE_DB_PATH,
    SETTINGS_KEY_DEFERRED_DB_PATH,
    SETTINGS_KEY_DEFERRED_DB_REASON,
    get_supported_schema_version,
)
from app.infra.settings import SettingsService
from app.ui.first_run_wizard import FirstRunWizardDialog


def _disable_background_health(monkeypatch) -> None:
    monkeypatch.setattr(FirstRunWizardDialog, "_refresh_health_summary", lambda self: None)


def _write_manifest(path: Path) -> None:
    payload = {
        "manifest_version": "1.0",
        "resources": [],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _create_db(path: Path, schema_version: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('schema_version', ?)",
            (str(schema_version),),
        )
        conn.commit()
    finally:
        conn.close()
    return path


def test_first_run_wizard_db_step_saves_selected_path(monkeypatch, qtbot, tmp_path):
    SettingsService.reset_instance()
    settings = SettingsService.get_instance()
    settings._settings.clear()
    settings.sync()
    _disable_background_health(monkeypatch)

    manifest_path = tmp_path / "resource_manifest.json"
    _write_manifest(manifest_path)
    settings.set_value("resources/manifest_path", str(manifest_path))
    settings.set_value("resources/data_root", str(tmp_path / "hdle_data"))
    settings.sync()

    schema_version = get_supported_schema_version()
    selected_db = _create_db(tmp_path / "selected.db", schema_version)

    dialog = FirstRunWizardDialog()
    qtbot.addWidget(dialog)
    dialog.show()

    dialog.db_browse_radio.setChecked(True)
    dialog.db_path_edit.setText(str(selected_db))

    assert dialog._apply_database_selection() is True
    assert settings.get_string(SETTINGS_KEY_ACTIVE_DB_PATH, "") == str(selected_db.resolve())


def test_first_run_wizard_clears_deferred_db_guard_on_selection(monkeypatch, qtbot, tmp_path):
    SettingsService.reset_instance()
    settings = SettingsService.get_instance()
    settings._settings.clear()
    settings.sync()
    _disable_background_health(monkeypatch)

    manifest_path = tmp_path / "resource_manifest.json"
    _write_manifest(manifest_path)
    settings.set_value("resources/manifest_path", str(manifest_path))
    settings.set_value("resources/data_root", str(tmp_path / "hdle_data"))
    settings.set_value(SETTINGS_KEY_DEFERRED_DB_PATH, str(tmp_path / "legacy.db"))
    settings.set_value(SETTINGS_KEY_DEFERRED_DB_REASON, "legacy db deferred")
    settings.sync()

    schema_version = get_supported_schema_version()
    selected_db = _create_db(tmp_path / "selected.db", schema_version)

    dialog = FirstRunWizardDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.db_browse_radio.setChecked(True)
    dialog.db_path_edit.setText(str(selected_db))

    assert dialog._apply_database_selection() is True
    assert settings.get_string(SETTINGS_KEY_DEFERRED_DB_PATH, "") == ""
    assert settings.get_string(SETTINGS_KEY_DEFERRED_DB_REASON, "") == ""


def test_first_run_wizard_db_step_mentions_restart_for_existing_db(monkeypatch, qtbot, tmp_path):
    SettingsService.reset_instance()
    settings = SettingsService.get_instance()
    settings._settings.clear()
    settings.sync()
    _disable_background_health(monkeypatch)

    manifest_path = tmp_path / "resource_manifest.json"
    _write_manifest(manifest_path)
    settings.set_value("resources/manifest_path", str(manifest_path))
    settings.set_value("resources/data_root", str(tmp_path / "hdle_data"))
    settings.sync()

    schema_version = get_supported_schema_version()
    selected_db = _create_db(tmp_path / "selected.db", schema_version)

    dialog = FirstRunWizardDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.db_browse_radio.setChecked(True)
    dialog.db_path_edit.setText(str(selected_db))
    dialog._update_db_step_state()

    text = dialog.db_status_label.text()
    assert "Restart is required to switch." in text


def test_first_run_wizard_db_step_mentions_default_local_first_guidance(monkeypatch, qtbot, tmp_path):
    SettingsService.reset_instance()
    settings = SettingsService.get_instance()
    settings._settings.clear()
    settings.sync()
    _disable_background_health(monkeypatch)

    manifest_path = tmp_path / "resource_manifest.json"
    _write_manifest(manifest_path)
    settings.set_value("resources/manifest_path", str(manifest_path))
    settings.set_value("resources/data_root", str(tmp_path / "hdle_data"))
    settings.sync()

    dialog = FirstRunWizardDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.db_default_radio.setChecked(True)
    dialog._update_db_step_state()

    text = dialog.db_status_label.text()
    assert "recommended local-first path" in text
    assert "Tools -> Switch Database" in text


def test_first_run_wizard_db_step_mentions_heavy_baseline_restart_guidance(monkeypatch, qtbot, tmp_path):
    SettingsService.reset_instance()
    settings = SettingsService.get_instance()
    settings._settings.clear()
    settings.sync()
    _disable_background_health(monkeypatch)

    manifest_path = tmp_path / "resource_manifest.json"
    _write_manifest(manifest_path)
    settings.set_value("resources/manifest_path", str(manifest_path))
    settings.set_value("resources/data_root", str(tmp_path / "hdle_data"))
    settings.sync()

    baseline_db = _create_db(tmp_path / "baseline.db", get_supported_schema_version())
    monkeypatch.setattr("app.ui.first_run_wizard.discover_baseline_db_path", lambda: baseline_db)
    monkeypatch.setattr("app.ui.first_run_wizard.STARTUP_DEFER_SIZE_THRESHOLD_BYTES", 1)

    dialog = FirstRunWizardDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.db_baseline_radio.setChecked(True)
    dialog._update_db_step_state()

    text = dialog.db_status_label.text()
    assert "finish the wizard and restart once" in text
    assert "Prefer one deliberate restart" in text
    assert "Baseline quick-pick is intended for explicit reconnect" in text
