"""Integration-level contract tests for AppWindow workspace navigation."""

import sqlite3
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import QWidget

from app.infra.settings import SettingsService
from app.ui.app_window import AppWindow, _HEBREW_SHORTCUT_KEY_MAP


class _StubProjectView(QWidget):
    back_to_dashboard = pyqtSignal()
    open_translation_management_requested = pyqtSignal(object)

    def __init__(self, project_id):
        super().__init__()
        self.project_id = int(project_id)
        self.project_created_at = ""
        self.focused_tabs = []
        self.load_project_calls = 0

    def focus_tab(self, tab_key: str) -> bool:
        self.focused_tabs.append(str(tab_key))
        return True

    def load_project(self) -> None:
        self.load_project_calls += 1


class _FakeWorker:
    def __init__(self, *, running=True, wait_result=False):
        self._running = running
        self._wait_result = wait_result
        self.wait_calls = []
        self.terminate_called = False

    def isRunning(self):
        return self._running

    def wait(self, timeout):
        self.wait_calls.append(timeout)
        if self._wait_result:
            self._running = False
        return self._wait_result

    def terminate(self):
        self.terminate_called = True
        self._running = False


def _fresh_window(monkeypatch, qtbot):
    SettingsService.reset_instance()
    settings = SettingsService.get_instance()
    settings._settings.clear()
    settings.set_value("workspace/active_workspace", "workspace.projects")
    settings.sync()

    monkeypatch.setattr(
        "app.ui.project_dashboard.ProjectDashboard.load_projects", lambda self: None
    )
    monkeypatch.setattr("app.ui.project_dashboard.ProjectService", lambda: object())
    monkeypatch.setattr("app.ui.app_window.ProjectService", lambda: object())
    window = AppWindow()
    qtbot.addWidget(window)
    window.show()
    return window


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


def test_no_duplicate_shortcut_bindings(monkeypatch, qtbot):
    window = _fresh_window(monkeypatch, qtbot)
    conflicts = window._collect_shortcut_conflicts()
    assert conflicts == {}


def test_pending_project_tab_routes_after_open(monkeypatch, qtbot):
    window = _fresh_window(monkeypatch, qtbot)

    monkeypatch.setattr("app.ui.app_window.ProjectView", _StubProjectView)
    monkeypatch.setattr(window, "_is_valid_project_id", lambda project_id: True)
    monkeypatch.setattr(
        window, "_lookup_project_name", lambda project_id: f"Project {int(project_id)}"
    )

    window._set_current_project_context(None, "")
    window._open_current_project_tab("terms")
    assert window._pending_project_tab == "terms"

    window.open_project(55)
    assert window._pending_project_tab is None
    current = window.stack.currentWidget()
    assert isinstance(current, _StubProjectView)
    assert current.focused_tabs == ["terms"]


def test_open_project_recreates_cached_view_when_identity_changed(monkeypatch, qtbot):
    window = _fresh_window(monkeypatch, qtbot)

    monkeypatch.setattr("app.ui.app_window.ProjectView", _StubProjectView)
    monkeypatch.setattr(window, "_is_valid_project_id", lambda project_id: True)
    monkeypatch.setattr(
        window, "_lookup_project_identity", lambda project_id: ("Recreated", "created-new")
    )

    stale = _StubProjectView(55)
    stale.project_created_at = "created-old"
    window.stack.addWidget(stale)
    window._project_instances[55] = stale
    window._register_workspace_instance("project:55", stale)

    window.open_project(55)
    current = window.stack.currentWidget()
    assert isinstance(current, _StubProjectView)
    assert current is not stale
    assert window._project_instances[55] is current
    assert window._is_widget_in_stack(stale) is False
    assert window.current_project_name == "Recreated"


def test_project_deleted_invalidates_runtime_and_recent_state(monkeypatch, qtbot):
    window = _fresh_window(monkeypatch, qtbot)

    monkeypatch.setattr(window, "_is_valid_project_id", lambda project_id: True)
    window.current_project_id = 7
    window.current_project_name = "Legacy"
    window._recent_project_ids = [7, 9]

    stale = _StubProjectView(7)
    stale.project_created_at = "created-old"
    window.stack.addWidget(stale)
    window._project_instances[7] = stale
    window._register_workspace_instance("project:7", stale)

    window._on_project_deleted(7)

    assert 7 not in window._project_instances
    assert window._is_widget_in_stack(stale) is False
    assert window.current_project_id is None
    assert 7 not in window._recent_project_ids


def test_expand_layout_shortcuts_adds_hebrew_variant(monkeypatch, qtbot):
    window = _fresh_window(monkeypatch, qtbot)
    seqs = window._expand_layout_shortcuts("Ctrl+Shift+T")
    values = [seq.toString() for seq in seqs]
    assert "Ctrl+Shift+T" in values
    assert f"Ctrl+Shift+{_HEBREW_SHORTCUT_KEY_MAP['T']}" in values


def test_collect_shortcut_conflicts_respects_multi_shortcuts(monkeypatch, qtbot):
    window = _fresh_window(monkeypatch, qtbot)

    a1 = QAction("A1", window)
    a1.setShortcuts(
        [QKeySequence("Ctrl+Shift+U"), QKeySequence(f"Ctrl+Shift+{_HEBREW_SHORTCUT_KEY_MAP['U']}")]
    )
    window.addAction(a1)

    a2 = QAction("A2", window)
    a2.setShortcut(QKeySequence(f"Ctrl+Shift+{_HEBREW_SHORTCUT_KEY_MAP['U']}"))
    window.addAction(a2)

    conflicts = window._collect_shortcut_conflicts()
    assert f"CTRL+SHIFT+{_HEBREW_SHORTCUT_KEY_MAP['U']}" in conflicts


def test_sidebar_audio_workspace_click_toggles_panel_visibility(monkeypatch, qtbot):
    window = _fresh_window(monkeypatch, qtbot)
    window.audio_player_dock.hide()

    window._on_sidebar_action("workspace.audio")
    assert window.audio_player_dock.isVisible() is True
    assert window._current_workspace_key() == "workspace.audio"

    window._on_sidebar_action("workspace.audio")
    assert window.audio_player_dock.isVisible() is False
    assert window._current_workspace_key() != "workspace.audio"


def test_maybe_open_imported_project_routes_to_new_project(monkeypatch, qtbot):
    window = _fresh_window(monkeypatch, qtbot)

    opened = []
    monkeypatch.setattr(window, "open_project", lambda project_id: opened.append(int(project_id)))

    class _Dialog:
        def should_open_project(self):
            return True

        def get_new_project_id(self):
            return 77

    window._maybe_open_imported_project(_Dialog())
    assert opened == [77]


def test_deferred_reconnect_prompt_mentions_single_restart_path(monkeypatch, qtbot, tmp_path):
    SettingsService.reset_instance()
    settings = SettingsService.get_instance()
    settings._settings.clear()
    settings.set_value("workspace/active_workspace", "workspace.projects")
    settings.sync()

    monkeypatch.setattr(
        "app.ui.project_dashboard.ProjectDashboard.load_projects", lambda self: None
    )
    monkeypatch.setattr("app.ui.project_dashboard.ProjectService", lambda: object())
    monkeypatch.setattr("app.ui.app_window.ProjectService", lambda: object())

    window = AppWindow()
    qtbot.addWidget(window)
    window.show()

    legacy_db = _create_db(tmp_path / "legacy.db", 41)
    settings.set_value("app/deferred_startup_db_path", str(legacy_db))
    settings.set_value("app/deferred_startup_db_reason", "legacy startup guard")
    settings.sync()

    monkeypatch.setattr("app.ui.app_window.STARTUP_DEFER_SIZE_THRESHOLD_BYTES", 1)

    info = type(
        "Info",
        (),
        {
            "exists": True,
            "schema_version": 41,
            "supported_schema_version": 42,
            "size_bytes": 2,
        },
    )()

    text = window._build_deferred_database_reconnect_message(
        deferred=legacy_db,
        info=info,
        deferred_reason="legacy startup guard",
        baseline=None,
        inspect_db_info=lambda path: info,
    )

    assert "choose one migrated DB, switch once" in text
    assert "longer restart while backup and migration finish" in text
    assert "safer option until you intentionally reconnect" in text
    assert "Deferred reason: legacy startup guard" in text


def test_app_window_close_event_waits_for_health_worker(monkeypatch, qtbot):
    window = _fresh_window(monkeypatch, qtbot)
    worker = _FakeWorker(running=True, wait_result=False)
    window._health_check_worker = worker

    window.close()

    assert worker.wait_calls == [1000, 1000]
    assert worker.terminate_called is True
