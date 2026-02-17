"""Scope chip tests for Translation Management panel."""

from app.infra.settings import SettingsService
from app.ui.translation_management_panel import TranslationManagementPanel


def _panel_without_initial_search(monkeypatch, project_id=None):
    monkeypatch.setattr(TranslationManagementPanel, "load_initial_data", lambda self: None)
    monkeypatch.setattr(TranslationManagementPanel, "perform_search", lambda self: None)
    return TranslationManagementPanel(project_id=project_id)


def test_tm_scope_defaults_to_current_project_when_context_exists(monkeypatch, qtbot):
    settings = SettingsService.get_instance()
    settings.set_value("tm_panel/scope_mode_project", "current_project")

    panel = _panel_without_initial_search(monkeypatch, project_id=33)
    qtbot.addWidget(panel)

    assert panel.scope_mode == "current_project"
    assert panel.selected_project_ids == [33]


def test_tm_scope_falls_back_to_global_without_project_context(monkeypatch, qtbot):
    settings = SettingsService.get_instance()
    settings.set_value("tm_panel/scope_mode_global", "current_project")

    panel = _panel_without_initial_search(monkeypatch, project_id=None)
    qtbot.addWidget(panel)

    assert panel.scope_mode == "global"
    assert panel.selected_project_ids is None


def test_tm_scope_switch_to_global_clears_project_filter(monkeypatch, qtbot):
    panel = _panel_without_initial_search(monkeypatch, project_id=44)
    qtbot.addWidget(panel)

    panel.on_scope_changed("global")

    assert panel.scope_mode == "global"
    assert panel.selected_project_ids is None
