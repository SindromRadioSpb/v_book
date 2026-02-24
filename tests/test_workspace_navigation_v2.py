"""Workspace navigation v2 tests."""

from PyQt6.QtCore import Qt

from app.ui.workspace_manager import SidebarWidget


def test_sidebar_primary_navigation_emits_workspace_actions(qtbot):
    sidebar = SidebarWidget()
    qtbot.addWidget(sidebar)

    with qtbot.waitSignal(sidebar.action_triggered, timeout=1000) as blocker:
        sidebar.projects_btn.click()
    assert blocker.args[0] == "workspace.projects"

    with qtbot.waitSignal(sidebar.action_triggered, timeout=1000) as blocker:
        sidebar.tm_btn.click()
    assert blocker.args[0] == "workspace.tm"

    with qtbot.waitSignal(sidebar.action_triggered, timeout=1000) as blocker:
        sidebar.user_dict_btn.click()
    assert blocker.args[0] == "workspace.user_dictionaries"

    with qtbot.waitSignal(sidebar.action_triggered, timeout=1000) as blocker:
        sidebar.audio_btn.click()
    assert blocker.args[0] == "workspace.audio"


def test_sidebar_tools_actions_still_available(qtbot):
    sidebar = SidebarWidget()
    qtbot.addWidget(sidebar)

    with qtbot.waitSignal(sidebar.action_triggered, timeout=1000) as blocker:
        sidebar.import_btn.click()
    assert blocker.args[0] == "tools.import_dictionary"

    with qtbot.waitSignal(sidebar.action_triggered, timeout=1000) as blocker:
        sidebar.coverage_btn.click()
    assert blocker.args[0] == "premium.coverage"

    with qtbot.waitSignal(sidebar.action_triggered, timeout=1000) as blocker:
        sidebar.verify_btn.click()
    assert blocker.args[0] == "tools.verification"

    with qtbot.waitSignal(sidebar.action_triggered, timeout=1000) as blocker:
        sidebar.refresh_badges_btn.click()
    assert blocker.args[0] == "workspace.refresh_badges"


def test_sidebar_active_workspace_switches_checked_state(qtbot):
    sidebar = SidebarWidget()
    qtbot.addWidget(sidebar)

    sidebar.set_active_workspace("workspace.tm")
    assert sidebar.tm_btn.isChecked() is True
    assert sidebar.projects_btn.isChecked() is False

    sidebar.set_active_workspace("workspace.audio")
    assert sidebar.audio_btn.isChecked() is True
    assert sidebar.tm_btn.isChecked() is False


def test_sidebar_current_project_card_disabled_links_when_missing_project(qtbot):
    sidebar = SidebarWidget()
    qtbot.addWidget(sidebar)
    sidebar.set_current_project(None, "", "All projects")

    assert sidebar.open_current_project_btn.isEnabled() is True
    assert sidebar.documents_link_btn.isEnabled() is False
    assert sidebar.sentences_link_btn.isEnabled() is False
    assert sidebar.terms_link_btn.isEnabled() is False


def test_sidebar_project_search_emits_workspace_open_project_action(qtbot):
    sidebar = SidebarWidget()
    qtbot.addWidget(sidebar)
    sidebar.set_project_catalog(
        [{"project_id": 7, "name": "Physics Basics"}, {"project_id": 11, "name": "Advanced Physics"}],
        recent_ids=[11],
    )

    sidebar.project_search_edit.setText("phys")
    qtbot.wait(320)

    item = sidebar.project_results_list.item(0)
    assert item is not None
    sidebar.project_results_list.setCurrentItem(item)

    with qtbot.waitSignal(sidebar.action_triggered, timeout=1000) as blocker:
        sidebar._on_project_result_activated(item)
    assert blocker.args[0].startswith("workspace.open_project:")

    # Keyboard Enter should trigger activation as well.
    with qtbot.waitSignal(sidebar.action_triggered, timeout=1000) as blocker:
        qtbot.keyClick(sidebar.project_search_edit, Qt.Key.Key_Return)
    assert blocker.args[0].startswith("workspace.open_project:")
