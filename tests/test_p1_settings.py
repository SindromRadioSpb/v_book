"""
Tests for P1 SettingsService.

Tests QSettings wrapper functionality, type safety, crash safety, and window geometry persistence.
"""

import json
import pytest
from unittest.mock import MagicMock

from PyQt6.QtCore import QByteArray, QSettings
from PyQt6.QtWidgets import QWidget

from app.infra.settings import SettingsService


@pytest.fixture
def settings():
    """Create fresh settings instance for each test."""
    SettingsService.reset_instance()
    service = SettingsService.get_instance()
    # Clear all settings before each test
    service._settings.clear()
    service.sync()
    yield service
    SettingsService.reset_instance()


class TestSettingsSingleton:
    """Test singleton pattern."""

    def test_get_instance_returns_same_instance(self):
        """Test that get_instance returns the same instance."""
        SettingsService.reset_instance()
        instance1 = SettingsService.get_instance()
        instance2 = SettingsService.get_instance()
        assert instance1 is instance2

    def test_reset_instance_clears_singleton(self):
        """Test that reset_instance allows new instance creation."""
        instance1 = SettingsService.get_instance()
        SettingsService.reset_instance()
        instance2 = SettingsService.get_instance()
        assert instance1 is not instance2


class TestBasicTypes:
    """Test get/set for basic types."""

    def test_string_roundtrip(self, settings):
        """Test string get/set roundtrip."""
        settings.set_value("test/string", "hello world")
        assert settings.get_string("test/string") == "hello world"

    def test_string_default(self, settings):
        """Test string default fallback."""
        assert settings.get_string("nonexistent", "default") == "default"

    def test_int_roundtrip(self, settings):
        """Test integer get/set roundtrip."""
        settings.set_value("test/int", 42)
        assert settings.get_int("test/int") == 42

    def test_int_default(self, settings):
        """Test integer default fallback."""
        assert settings.get_int("nonexistent", 123) == 123

    def test_bool_roundtrip(self, settings):
        """Test boolean get/set roundtrip."""
        settings.set_value("test/bool_true", True)
        settings.set_value("test/bool_false", False)
        assert settings.get_bool("test/bool_true") is True
        assert settings.get_bool("test/bool_false") is False

    def test_bool_default(self, settings):
        """Test boolean default fallback."""
        assert settings.get_bool("nonexistent", True) is True
        assert settings.get_bool("nonexistent", False) is False

    def test_bytes_roundtrip(self, settings):
        """Test bytes get/set roundtrip."""
        data = b"\x00\x01\x02\xff"
        settings.set_value("test/bytes", QByteArray(data))
        assert settings.get_bytes("test/bytes") == data

    def test_bytes_default(self, settings):
        """Test bytes default fallback."""
        assert settings.get_bytes("nonexistent", b"default") == b"default"


class TestJSON:
    """Test JSON serialization."""

    def test_json_dict_roundtrip(self, settings):
        """Test JSON dict roundtrip."""
        data = {"key": "value", "number": 42, "nested": {"a": 1}}
        settings.set_json("test/json", data)
        assert settings.get_json("test/json") == data

    def test_json_list_roundtrip(self, settings):
        """Test JSON list roundtrip."""
        data = [1, 2, "three", {"four": 4}]
        settings.set_json("test/json", data)
        assert settings.get_json("test/json") == data

    def test_json_corrupt_fallback(self, settings):
        """Test corrupt JSON returns default."""
        settings.set_value("test/corrupt", "{not valid json")
        assert settings.get_json("test/corrupt", {"fallback": True}) == {"fallback": True}

    def test_json_empty_fallback(self, settings):
        """Test empty JSON returns default."""
        assert settings.get_json("nonexistent", []) == []


class TestWindowGeometry:
    """Test window geometry persistence."""

    def test_window_geometry_roundtrip_mock(self, settings):
        """Test window geometry save/restore with mock."""
        # Create mock widget (don't use spec to allow any attribute)
        widget = MagicMock()
        geometry_data = QByteArray(b"\x01\x02\x03")
        state_data = QByteArray(b"\x04\x05\x06")

        widget.saveGeometry.return_value = geometry_data
        widget.saveState.return_value = state_data
        widget.restoreGeometry.return_value = True
        widget.restoreState.return_value = True

        # Save
        settings.save_window_geometry(widget)
        settings.sync()

        # Verify save was called
        widget.saveGeometry.assert_called_once()
        widget.saveState.assert_called_once()

        # Restore
        widget2 = MagicMock()
        widget2.restoreGeometry.return_value = True
        widget2.restoreState.return_value = True

        result = settings.restore_window_geometry(widget2)

        # Verify restore was called and succeeded
        assert result is True
        widget2.restoreGeometry.assert_called_once()

    def test_restore_window_geometry_empty_returns_false(self, settings):
        """Test restore on empty settings returns False."""
        widget = MagicMock()
        result = settings.restore_window_geometry(widget)
        assert result is False


class TestHeaderState:
    """Test table header persistence."""

    def test_header_state_roundtrip_mock(self, settings):
        """Test header state save/restore with mock."""
        from PyQt6.QtWidgets import QHeaderView

        # Create mock header
        header = MagicMock(spec=QHeaderView)
        state_data = QByteArray(b"\x01\x02\x03\x04")
        header.saveState.return_value = state_data
        header.restoreState.return_value = True

        # Save
        settings.save_header_state("test_table", header)
        settings.sync()

        # Verify save was called
        header.saveState.assert_called_once()

        # Restore
        header2 = MagicMock(spec=QHeaderView)
        header2.restoreState.return_value = True

        result = settings.restore_header_state("test_table", header2)

        # Verify restore was called and succeeded
        assert result is True
        header2.restoreState.assert_called_once()

    def test_restore_header_state_empty_returns_false(self, settings):
        """Test restore on empty settings returns False."""
        from PyQt6.QtWidgets import QHeaderView

        header = MagicMock(spec=QHeaderView)
        header.restoreState.return_value = False
        result = settings.restore_header_state("nonexistent_table", header)
        assert result is False


class TestRemoveAndSync:
    """Test remove and sync operations."""

    def test_remove_key(self, settings):
        """Test removing a key."""
        settings.set_value("test/remove", "value")
        assert settings.get_string("test/remove") == "value"

        settings.remove("test/remove")
        assert settings.get_string("test/remove", "default") == "default"

    def test_sync_no_crash(self, settings):
        """Test sync doesn't crash."""
        settings.set_value("test/sync", "value")
        settings.sync()
        # No assertion - just verify no crash
