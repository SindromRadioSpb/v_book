"""Scope behavior tests for User Dictionaries view."""

from app.infra.settings import SettingsService
from app.ui.user_dictionaries_view import UserDictionariesView


def _view_without_db_load(monkeypatch, project_id=None):
    monkeypatch.setattr(UserDictionariesView, "load_dictionaries", lambda self: None)
    monkeypatch.setattr(UserDictionariesView, "load_items", lambda self: None)
    monkeypatch.setattr("app.ui.user_dictionaries_view.DBService.get_instance", lambda: object())
    return UserDictionariesView(project_id=project_id)


def test_default_scope_current_project_when_project_open(monkeypatch, qtbot):
    settings = SettingsService.get_instance()
    settings.set_value("user_dict/scope_mode_project", "current_project")

    view = _view_without_db_load(monkeypatch, project_id=77)
    qtbot.addWidget(view)

    assert view.scope_mode == "current_project"
    filters = view.build_filters()
    assert filters["origin_project_id"] == 77


def test_default_scope_all_without_project_context(monkeypatch, qtbot):
    settings = SettingsService.get_instance()
    settings.set_value("user_dict/scope_mode_global", "current_project")

    view = _view_without_db_load(monkeypatch, project_id=None)
    qtbot.addWidget(view)

    assert view.scope_mode == "all"
    filters = view.build_filters()
    assert "origin_project_id" not in filters


def test_scope_toggle_to_all_removes_project_filter(monkeypatch, qtbot):
    settings = SettingsService.get_instance()
    settings.set_value("user_dict/scope_mode_project", "current_project")

    view = _view_without_db_load(monkeypatch, project_id=51)
    qtbot.addWidget(view)

    assert view.scope_mode == "current_project"
    view.on_scope_changed("all")

    assert view.scope_mode == "all"
    filters = view.build_filters()
    assert "origin_project_id" not in filters


def test_scope_persistence(monkeypatch, qtbot):
    settings = SettingsService.get_instance()

    view = _view_without_db_load(monkeypatch, project_id=12)
    qtbot.addWidget(view)
    view.on_scope_changed("all")

    assert settings.get_string("user_dict/scope_mode_project", "") == "all"

    view2 = _view_without_db_load(monkeypatch, project_id=12)
    qtbot.addWidget(view2)
    assert view2.scope_mode == "all"


def test_ud_cross_link_to_tm_is_discoverable(monkeypatch, qtbot):
    view = _view_without_db_load(monkeypatch, project_id=15)
    qtbot.addWidget(view)
    view.show()

    assert view.open_tm_btn.isVisible() is True
    assert view.open_tm_btn.isEnabled() is True
