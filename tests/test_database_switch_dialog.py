"""Tests for database switch dialog persistence and restart flow."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.infra.db_path_resolver import (
    SETTINGS_KEY_ACTIVE_DB_PATH,
    SETTINGS_KEY_DEFERRED_DB_PATH,
    SETTINGS_KEY_DEFERRED_DB_REASON,
    get_supported_schema_version,
)
from app.infra.settings import SettingsService
from app.ui.database_switch_dialog import DatabaseSwitchDialog


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


def test_build_restart_command_for_source_mode():
    command = DatabaseSwitchDialog.build_restart_command(Path("C:/tmp/test.db"))
    assert "-m" in command
    assert "app.main" in command
    assert "--db-path" in command


def test_restart_application_invokes_subprocess(monkeypatch):
    captured = {}

    def _fake_popen(command):
        captured["command"] = command
        return object()

    monkeypatch.setattr("app.ui.database_switch_dialog.subprocess.Popen", _fake_popen)
    monkeypatch.setattr(
        DatabaseSwitchDialog,
        "build_restart_command",
        lambda db_path: ["python", "-m", "app.main", "--db-path", str(db_path)],
    )
    monkeypatch.setattr("app.ui.database_switch_dialog.QApplication.instance", lambda: None)

    assert DatabaseSwitchDialog.restart_application(Path("C:/tmp/test.db")) is True
    assert captured["command"][:4] == ["python", "-m", "app.main", "--db-path"]
    assert captured["command"][4].endswith("test.db")


def test_switch_dialog_persists_selected_db_and_restarts(qtbot, tmp_path):
    SettingsService.reset_instance()
    settings = SettingsService.get_instance()
    settings._settings.clear()
    settings.sync()

    schema_version = get_supported_schema_version()
    current_db = _create_db(tmp_path / "current.db", schema_version)
    target_db = _create_db(tmp_path / "target.db", schema_version)

    restarted = []

    def _restart(path: Path) -> bool:
        restarted.append(Path(path).resolve())
        return True

    dialog = DatabaseSwitchDialog(
        current_db_path=current_db,
        settings=settings,
        restart_callback=_restart,
    )
    qtbot.addWidget(dialog)
    dialog.show()

    dialog.browse_radio.setChecked(True)
    dialog.browse_edit.setText(str(target_db))
    dialog._on_switch_and_restart()

    assert settings.get_string(SETTINGS_KEY_ACTIVE_DB_PATH, "") == str(target_db.resolve())
    assert restarted == [target_db.resolve()]


def test_switch_dialog_clears_deferred_db_guard(qtbot, tmp_path):
    SettingsService.reset_instance()
    settings = SettingsService.get_instance()
    settings._settings.clear()
    settings.set_value(SETTINGS_KEY_DEFERRED_DB_PATH, str(tmp_path / "legacy.db"))
    settings.set_value(SETTINGS_KEY_DEFERRED_DB_REASON, "legacy db deferred")
    settings.sync()

    schema_version = get_supported_schema_version()
    current_db = _create_db(tmp_path / "current.db", schema_version)
    target_db = _create_db(tmp_path / "target.db", schema_version)

    dialog = DatabaseSwitchDialog(
        current_db_path=current_db,
        settings=settings,
        restart_callback=lambda _path: True,
    )
    qtbot.addWidget(dialog)
    dialog.show()

    dialog.browse_radio.setChecked(True)
    dialog.browse_edit.setText(str(target_db))
    dialog._on_switch_and_restart()

    assert settings.get_string(SETTINGS_KEY_DEFERRED_DB_PATH, "") == ""
    assert settings.get_string(SETTINGS_KEY_DEFERRED_DB_REASON, "") == ""


def test_switch_dialog_surfaces_deferred_reconnect_guidance(qtbot, tmp_path):
    SettingsService.reset_instance()
    settings = SettingsService.get_instance()
    settings._settings.clear()
    schema_version = get_supported_schema_version() - 1
    current_db = _create_db(tmp_path / "current.db", get_supported_schema_version())
    legacy_db = _create_db(tmp_path / "legacy.db", schema_version)
    settings.set_value(SETTINGS_KEY_DEFERRED_DB_PATH, str(legacy_db))
    settings.set_value(SETTINGS_KEY_DEFERRED_DB_REASON, "legacy db deferred")
    settings.sync()

    dialog = DatabaseSwitchDialog(
        current_db_path=current_db,
        settings=settings,
        restart_callback=lambda _path: True,
    )
    qtbot.addWidget(dialog)
    dialog.show()

    dialog.browse_radio.setChecked(True)
    dialog.browse_edit.setText(str(legacy_db))

    guidance = dialog.reconnect_guidance_label.text()
    assert "explicit reconnect path" in guidance
    assert "Deferred reason: legacy db deferred" in guidance
    assert "backup and migration" in guidance
    assert "switch once" in guidance


def test_switch_dialog_default_profile_guidance_mentions_fastest_startup(qtbot, tmp_path):
    SettingsService.reset_instance()
    settings = SettingsService.get_instance()
    settings._settings.clear()
    settings.sync()
    current_db = _create_db(tmp_path / "current.db", get_supported_schema_version())

    dialog = DatabaseSwitchDialog(
        current_db_path=current_db,
        settings=settings,
        restart_callback=lambda _path: True,
    )
    qtbot.addWidget(dialog)
    dialog.show()

    assert "fastest local startup" in dialog.reconnect_guidance_label.text()


def test_switch_dialog_heavy_baseline_guidance_mentions_backup_and_reference_workspace(
    monkeypatch, qtbot, tmp_path
):
    SettingsService.reset_instance()
    settings = SettingsService.get_instance()
    settings._settings.clear()
    settings.sync()

    current_db = _create_db(tmp_path / "current.db", get_supported_schema_version())
    baseline_db = _create_db(tmp_path / "baseline.db", get_supported_schema_version())

    monkeypatch.setattr("app.ui.database_switch_dialog.discover_baseline_db_path", lambda: baseline_db)
    monkeypatch.setattr(
        "app.ui.database_switch_dialog.classify_db_profile",
        lambda path, settings=None: "Baseline (dev)" if Path(path).resolve() == baseline_db.resolve() else "Custom",
    )
    monkeypatch.setattr("app.ui.database_switch_dialog.STARTUP_DEFER_SIZE_THRESHOLD_BYTES", 1)

    dialog = DatabaseSwitchDialog(
        current_db_path=current_db,
        settings=settings,
        restart_callback=lambda _path: True,
    )
    qtbot.addWidget(dialog)
    dialog.show()

    dialog.baseline_radio.setChecked(True)
    dialog._update_selected_state()

    guidance = dialog.reconnect_guidance_label.text()
    assert "switch once" in guidance
    assert "creating a backup" in guidance
    assert "large reference workspace next" in guidance
