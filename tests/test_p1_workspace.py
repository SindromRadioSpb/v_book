"""
Tests for P1 WorkspaceManager.

Tests workspace layout, sidebar toggle, stack operations, and layout serialization.
"""

import pytest
from unittest.mock import MagicMock

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import QByteArray

from app.ui.workspace_manager import WorkspaceManager, SidebarWidget


class TestSidebarWidget:
    """Test sidebar widget."""

    def test_sidebar_emits_action_signals(self, qtbot):
        """Test sidebar emits action_triggered signal."""
        sidebar = SidebarWidget()
        qtbot.addWidget(sidebar)

        # Capture signals
        with qtbot.waitSignal(sidebar.action_triggered, timeout=1000) as blocker:
            sidebar.import_btn.click()

        assert blocker.args[0] == "tools.import_dictionary"

    def test_sidebar_has_all_action_buttons(self, qtbot):
        """Test sidebar has all expected buttons."""
        sidebar = SidebarWidget()
        qtbot.addWidget(sidebar)

        # Navigation buttons
        assert sidebar.dashboard_btn is not None
        assert "Dashboard" in sidebar.dashboard_btn.text()

        # Tool buttons
        assert sidebar.import_btn is not None
        assert sidebar.tm_btn is not None
        assert sidebar.verify_btn is not None

        # Verify tooltips contain shortcuts
        assert "Ctrl+Shift+I" in sidebar.import_btn.toolTip()
        assert "Ctrl+Shift+T" in sidebar.tm_btn.toolTip()
        assert "Ctrl+Shift+V" in sidebar.verify_btn.toolTip()


class TestWorkspaceManager:
    """Test workspace manager."""

    def test_default_layout(self, qtbot):
        """Test workspace initializes with sidebar hidden."""
        workspace = WorkspaceManager()
        qtbot.addWidget(workspace)

        assert workspace.sidebar.isVisible() is False
        assert workspace.stack is not None
        assert workspace.splitter is not None

    def test_toggle_sidebar(self, qtbot):
        """Test sidebar toggle functionality."""
        workspace = WorkspaceManager()
        qtbot.addWidget(workspace)
        workspace.show()  # Must show widget for visibility checks

        # Initially hidden
        assert workspace.sidebar.isVisible() is False

        # Toggle to show
        with qtbot.waitSignal(workspace.layout_changed, timeout=1000):
            workspace.toggle_sidebar()
        assert workspace.sidebar.isVisible() is True

        # Toggle to hide
        with qtbot.waitSignal(workspace.layout_changed, timeout=1000):
            workspace.toggle_sidebar()
        assert workspace.sidebar.isVisible() is False

    def test_stack_operations(self, qtbot):
        """Test stack operations through workspace."""
        workspace = WorkspaceManager()
        qtbot.addWidget(workspace)

        # Add widgets to stack
        widget1 = QWidget()
        widget2 = QWidget()

        workspace.stack.addWidget(widget1)
        workspace.stack.addWidget(widget2)

        assert workspace.stack.count() == 2

        # Switch between widgets
        workspace.stack.setCurrentWidget(widget1)
        assert workspace.stack.currentWidget() is widget1

        workspace.stack.setCurrentWidget(widget2)
        assert workspace.stack.currentWidget() is widget2

        # Remove widgets
        workspace.stack.removeWidget(widget1)
        assert workspace.stack.count() == 1

    def test_save_layout(self, qtbot):
        """Test layout serialization."""
        workspace = WorkspaceManager()
        qtbot.addWidget(workspace)
        workspace.show()  # Must show widget for visibility checks

        # Show sidebar and save layout
        workspace.sidebar.show()
        layout = workspace.save_layout()

        assert "layout_schema_version" in layout
        assert layout["layout_schema_version"] == WorkspaceManager.LAYOUT_SCHEMA_VERSION
        assert layout["sidebar_visible"] is True
        assert "splitter_state" in layout
        assert isinstance(layout["splitter_state"], str)  # Hex string

    def test_restore_layout_success(self, qtbot):
        """Test layout restoration with valid data."""
        workspace = WorkspaceManager()
        qtbot.addWidget(workspace)
        workspace.show()  # Must show widget for visibility checks

        # Save layout
        workspace.sidebar.show()
        layout = workspace.save_layout()

        # Hide sidebar
        workspace.sidebar.hide()

        # Restore
        success = workspace.restore_layout(layout)
        assert success is True
        assert workspace.sidebar.isVisible() is True

    def test_restore_layout_version_mismatch(self, qtbot):
        """Test layout restoration fails on version mismatch."""
        workspace = WorkspaceManager()
        qtbot.addWidget(workspace)

        # Invalid version
        layout = {
            "layout_schema_version": 999,
            "sidebar_visible": True,
            "splitter_state": "00"
        }

        success = workspace.restore_layout(layout)
        assert success is False

    def test_restore_layout_corrupt_data(self, qtbot):
        """Test layout restoration fails on corrupt data."""
        workspace = WorkspaceManager()
        qtbot.addWidget(workspace)
        workspace.show()  # Must show widget

        # Invalid hex
        layout = {
            "layout_schema_version": 1,
            "sidebar_visible": True,
            "splitter_state": "not_hex"
        }
        success = workspace.restore_layout(layout)
        assert success is False

    def test_reset_to_default(self, qtbot):
        """Test reset to default layout."""
        workspace = WorkspaceManager()
        qtbot.addWidget(workspace)
        workspace.show()  # Must show widget for visibility checks

        # Show sidebar
        workspace.sidebar.show()
        assert workspace.sidebar.isVisible() is True

        # Reset
        workspace.reset_to_default()
        assert workspace.sidebar.isVisible() is False
