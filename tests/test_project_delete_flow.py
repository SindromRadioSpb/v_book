"""Project delete UI flow regression tests."""

from __future__ import annotations

from types import SimpleNamespace

from app.ui.project_dashboard import ProjectDashboard


def test_delete_project_updates_dashboard(monkeypatch, qtbot):
    monkeypatch.setattr(
        "app.services.project_service.DBService.get_instance",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(ProjectDashboard, "load_projects", lambda self: None)
    monkeypatch.setattr("app.ui.project_dashboard.show_info", lambda *args, **kwargs: None)

    view = ProjectDashboard()
    qtbot.addWidget(view)

    refreshed = []
    monkeypatch.setattr(view, "load_projects", lambda: refreshed.append(True))

    report = SimpleNamespace(
        project_id=12,
        success=True,
        project_name="P",
        corpora_deleted=1,
        documents_deleted=2,
        sentences_deleted=3,
        lemmas_deleted=4,
        ngrams_deleted=5,
        term_cards_deleted=6,
    )

    view._on_delete_finished(report)
    assert refreshed == [True]
    assert "deleted" in view.status_label.text().lower()


def test_delete_project_failure_shows_error(monkeypatch, qtbot):
    monkeypatch.setattr(
        "app.services.project_service.DBService.get_instance",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(ProjectDashboard, "load_projects", lambda self: None)
    monkeypatch.setattr("app.ui.project_dashboard.show_error", lambda *args, **kwargs: None)

    view = ProjectDashboard()
    qtbot.addWidget(view)

    report = SimpleNamespace(success=False, error_message="database is locked")
    view._on_delete_finished(report)
    assert "failed" in view.status_label.text().lower()


def test_delete_project_emits_project_deleted_signal(monkeypatch, qtbot):
    monkeypatch.setattr(
        "app.services.project_service.DBService.get_instance",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(ProjectDashboard, "load_projects", lambda self: None)
    monkeypatch.setattr("app.ui.project_dashboard.show_info", lambda *args, **kwargs: None)

    view = ProjectDashboard()
    qtbot.addWidget(view)

    report = SimpleNamespace(
        project_id=77,
        success=True,
        project_name="Deleted",
        corpora_deleted=0,
        documents_deleted=0,
        sentences_deleted=0,
        lemmas_deleted=0,
        ngrams_deleted=0,
        term_cards_deleted=0,
    )

    with qtbot.waitSignal(view.project_deleted, timeout=1000) as blocker:
        view._on_delete_finished(report)
    assert blocker.args == [77]
