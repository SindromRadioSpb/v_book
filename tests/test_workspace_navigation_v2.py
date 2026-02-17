"""Workspace navigation v2 tests."""

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
