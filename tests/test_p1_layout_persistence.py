"""
Tests for P1 Layout Persistence.

Tests workspace layout save/restore, corrupt data fallback, and autosave debouncing.
"""

import json
import pytest
from unittest.mock import MagicMock, patch

from PyQt6.QtCore import Qt

from app.infra.settings import SettingsService
from app.ui.workspace_manager import WorkspaceManager


@pytest.fixture
def settings():
    """Create fresh settings instance for each test."""
    SettingsService.reset_instance()
    service = SettingsService.get_instance()
    service._settings.clear()
    service.sync()
    yield service
    SettingsService.reset_instance()


class TestLayoutPersistence:
    """Test layout save/restore with settings."""

    def test_save_load_roundtrip(self, settings, qtbot):
        """Test layout save/restore roundtrip."""
        workspace = WorkspaceManager()
        qtbot.addWidget(workspace)
        workspace.show()

        # Show sidebar
        workspace.sidebar.show()

        # Save layout
        layout = workspace.save_layout()
        settings.set_json("workspace/layout", layout)
        settings.sync()

        # Create new workspace
        workspace2 = WorkspaceManager()
        qtbot.addWidget(workspace2)
        workspace2.show()

        # Initially hidden
        assert workspace2.sidebar.isVisible() is False

        # Restore layout
        loaded_layout = settings.get_json("workspace/layout")
        success = workspace2.restore_layout(loaded_layout)
        assert success is True
        assert workspace2.sidebar.isVisible() is True

    def test_corrupt_json_fallback(self, settings, qtbot):
        """Test corrupt JSON returns None from get_json."""
        workspace = WorkspaceManager()
        qtbot.addWidget(workspace)
        workspace.show()

        # Store corrupt JSON
        settings.set_value("workspace/layout", "{not valid json")
        settings.sync()

        # Load should return None (fallback)
        layout = settings.get_json("workspace/layout", None)
        assert layout is None

    def test_version_mismatch_fallback(self, settings, qtbot):
        """Test version mismatch triggers fallback."""
        workspace = WorkspaceManager()
        qtbot.addWidget(workspace)
        workspace.show()

        # Save layout with wrong version
        layout = {"layout_schema_version": 999, "sidebar_visible": True, "splitter_state": "00"}
        settings.set_json("workspace/layout", layout)
        settings.sync()

        # Restore should fail
        loaded_layout = settings.get_json("workspace/layout")
        success = workspace.restore_layout(loaded_layout)
        assert success is False

    def test_missing_keys_fallback(self, settings, qtbot):
        """Test missing keys trigger fallback."""
        workspace = WorkspaceManager()
        qtbot.addWidget(workspace)
        workspace.show()

        # Save layout with missing keys
        layout = {"layout_schema_version": 1}
        settings.set_json("workspace/layout", layout)
        settings.sync()

        # Restore should fail
        loaded_layout = settings.get_json("workspace/layout")
        success = workspace.restore_layout(loaded_layout)
        assert success is False

    def test_autosave_debounce(self, settings, qtbot):
        """Test autosave is debounced (500ms)."""
        workspace = WorkspaceManager()
        qtbot.addWidget(workspace)
        workspace.show()

        # Track signal emissions
        signal_count = []

        def on_layout_changed():
            signal_count.append(1)

        workspace.layout_changed.connect(on_layout_changed)

        # Move splitter multiple times rapidly
        workspace.splitter.moveSplitter(100, 0)
        workspace.splitter.moveSplitter(200, 0)
        workspace.splitter.moveSplitter(300, 0)

        # Should not have emitted yet (still in debounce window)
        qtbot.wait(100)  # Wait less than debounce interval
        assert len(signal_count) == 0

        # Wait for debounce to complete
        qtbot.wait(500)

        # Should have emitted exactly once
        assert len(signal_count) == 1

    def test_toggle_sidebar_emits_immediately(self, settings, qtbot):
        """Test toggle sidebar emits immediately (not debounced)."""
        workspace = WorkspaceManager()
        qtbot.addWidget(workspace)
        workspace.show()

        # Catch signal
        with qtbot.waitSignal(workspace.layout_changed, timeout=100):
            workspace.toggle_sidebar()

        # Signal should have been emitted immediately
