"""ProjectDashboard governance dialog wiring tests."""

from __future__ import annotations

from types import SimpleNamespace

from app.domain.dto import ProjectStats
from app.ui.project_dashboard import ProjectDashboard


def test_project_dashboard_enables_governance_button_on_selection(monkeypatch, qtbot):
    monkeypatch.setattr(
        "app.services.project_service.DBService.get_instance",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(ProjectDashboard, "load_projects", lambda self: None)

    view = ProjectDashboard()
    qtbot.addWidget(view)

    view.project_model.update_projects(
        [
            ProjectStats(
                project_id=5,
                name="Governance Project",
                total_docs=10,
                processed_docs=9,
                total_lemmas=100,
                total_ngrams=40,
                is_general_corpus=False,
            )
        ]
    )

    assert view.governance_btn.isEnabled() is False
    view.project_table.selectRow(0)
    view.on_selection_changed()
    assert view.governance_btn.isEnabled() is True


def test_project_dashboard_opens_governance_dialog_for_selected_project(monkeypatch, qtbot):
    monkeypatch.setattr(
        "app.services.project_service.DBService.get_instance",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(ProjectDashboard, "load_projects", lambda self: None)

    opened = {}

    class _FakeDialog:
        def __init__(self, project_id, project_name, parent=None, **_kwargs):
            opened["project_id"] = int(project_id)
            opened["project_name"] = str(project_name)
            opened["parent"] = parent
            self.project_id = int(project_id)

        def setAttribute(self, *_args, **_kwargs):
            return None

        @property
        def destroyed(self):
            class _Signal:
                @staticmethod
                def connect(*_args, **_kwargs):
                    return None

            return _Signal()

        def show(self):
            opened["show"] = True

        def raise_(self):
            opened["raise"] = True

        def activateWindow(self):
            opened["activate"] = True

        def close(self):
            opened["close"] = True

    monkeypatch.setattr("app.ui.project_dashboard.ProjectArtifactGovernanceDialog", _FakeDialog)

    view = ProjectDashboard()
    qtbot.addWidget(view)
    view.project_model.update_projects(
        [
            ProjectStats(
                project_id=7,
                name="Ref Project",
                total_docs=5,
                processed_docs=5,
                total_lemmas=20,
                total_ngrams=10,
                is_general_corpus=True,
            )
        ]
    )
    view.project_table.selectRow(0)
    view.on_selection_changed()

    view.on_open_governance()

    assert opened["project_id"] == 7
    assert opened["project_name"] == "Ref Project"
    assert opened["show"] is True
    assert opened["raise"] is True
    assert opened["activate"] is True
