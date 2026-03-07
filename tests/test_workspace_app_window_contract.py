"""Integration-level contract tests for AppWindow workspace navigation."""

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


def _fresh_window(monkeypatch, qtbot):
    SettingsService.reset_instance()
    settings = SettingsService.get_instance()
    settings._settings.clear()
    settings.set_value("workspace/active_workspace", "workspace.projects")
    settings.sync()

    monkeypatch.setattr("app.ui.project_dashboard.ProjectDashboard.load_projects", lambda self: None)
    monkeypatch.setattr("app.ui.project_dashboard.ProjectService", lambda: object())
    monkeypatch.setattr("app.ui.app_window.ProjectService", lambda: object())
    window = AppWindow()
    qtbot.addWidget(window)
    window.show()
    return window


def test_no_duplicate_shortcut_bindings(monkeypatch, qtbot):
    window = _fresh_window(monkeypatch, qtbot)
    conflicts = window._collect_shortcut_conflicts()
    assert conflicts == {}


def test_pending_project_tab_routes_after_open(monkeypatch, qtbot):
    window = _fresh_window(monkeypatch, qtbot)

    monkeypatch.setattr("app.ui.app_window.ProjectView", _StubProjectView)
    monkeypatch.setattr(window, "_is_valid_project_id", lambda project_id: True)
    monkeypatch.setattr(window, "_lookup_project_name", lambda project_id: f"Project {int(project_id)}")

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
    monkeypatch.setattr(window, "_lookup_project_identity", lambda project_id: ("Recreated", "created-new"))

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
    a1.setShortcuts([QKeySequence("Ctrl+Shift+U"), QKeySequence(f"Ctrl+Shift+{_HEBREW_SHORTCUT_KEY_MAP['U']}")])
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
