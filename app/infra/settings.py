"""
SettingsService - QSettings wrapper for persistent application state.

Provides type-safe access to QSettings with INI format for portability.
Handles window geometry, layout state, and table configurations.
"""

import json
import logging
from typing import Any, Optional

from PyQt6.QtCore import QByteArray, QSettings
from PyQt6.QtWidgets import QHeaderView, QWidget

logger = logging.getLogger(__name__)


class SettingsService:
    """Singleton QSettings wrapper (INI format, cross-platform)."""

    _instance: Optional['SettingsService'] = None

    def __init__(self):
        """Initialize QSettings with INI format for portability."""
        self._settings = QSettings(
            QSettings.Format.IniFormat,
            QSettings.Scope.UserScope,
            "HDLE_Premium",
            "HDLE_Premium"
        )
        logger.info(f"Settings initialized at: {self._settings.fileName()}")

    @classmethod
    def get_instance(cls) -> 'SettingsService':
        """Get or create singleton instance."""
        if cls._instance is not None:
            try:
                # pytest-qt can tear down QApplication between tests, invalidating
                # underlying C++ QSettings object held by singleton.
                cls._instance._settings.fileName()
            except RuntimeError:
                cls._instance = None
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls):
        """Reset singleton instance (for tests)."""
        cls._instance = None

    def get_string(self, key: str, default: str = "") -> str:
        """Get string value."""
        return self._settings.value(key, default, type=str)

    def get_int(self, key: str, default: int = 0) -> int:
        """Get integer value."""
        return self._settings.value(key, default, type=int)

    def get_bool(self, key: str, default: bool = False) -> bool:
        """Get boolean value."""
        return self._settings.value(key, default, type=bool)

    def get_bytes(self, key: str, default: bytes = b"") -> bytes:
        """Get bytes value (QByteArray stored as bytes)."""
        value = self._settings.value(key, default)
        if isinstance(value, QByteArray):
            return bytes(value)
        return default

    def get_json(self, key: str, default: Any = None) -> Any:
        """Get JSON value with fallback on parse errors."""
        json_str = self.get_string(key, "")
        if not json_str:
            return default

        # Backward compatibility: some callers may have saved native list/dict.
        if isinstance(json_str, (list, dict)):
            return json_str

        try:
            return json.loads(json_str)
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning(f"Failed to parse JSON for key '{key}': {e}")
            return default

    def set_value(self, key: str, value: Any):
        """Set value (auto-converts Python types to QVariant)."""
        self._settings.setValue(key, value)

    def set_json(self, key: str, value: Any):
        """Set JSON value (serializes to string)."""
        json_str = json.dumps(value, ensure_ascii=False)
        self.set_value(key, json_str)

    def remove(self, key: str):
        """Remove key from settings."""
        self._settings.remove(key)

    def sync(self):
        """Force write settings to disk."""
        self._settings.sync()

    # Window geometry helpers

    def save_window_geometry(self, window: QWidget):
        """Save window geometry and state."""
        try:
            self.set_value("window/geometry", window.saveGeometry())
            if hasattr(window, 'saveState'):
                self.set_value("window/state", window.saveState())
            logger.debug("Window geometry saved")
        except Exception as e:
            logger.error(f"Failed to save window geometry: {e}")

    def restore_window_geometry(self, window: QWidget) -> bool:
        """
        Restore window geometry and state.

        Returns:
            True if restored successfully, False otherwise (crash-safe)
        """
        try:
            geometry = self.get_bytes("window/geometry")
            if geometry:
                success = window.restoreGeometry(QByteArray(geometry))
                if not success:
                    logger.warning("Failed to restore window geometry")
                    return False

                if hasattr(window, 'restoreState'):
                    state = self.get_bytes("window/state")
                    if state:
                        window.restoreState(QByteArray(state))

                logger.debug("Window geometry restored")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to restore window geometry: {e}")
            return False

    # Table header helpers

    def save_header_state(self, table_id: str, header: QHeaderView):
        """Save table header state (column order, widths, sort)."""
        try:
            key = f"table/{table_id}/header_state"
            self.set_value(key, header.saveState())
            logger.debug(f"Header state saved for '{table_id}'")
        except Exception as e:
            logger.error(f"Failed to save header state for '{table_id}': {e}")

    def restore_header_state(self, table_id: str, header: QHeaderView) -> bool:
        """
        Restore table header state.

        Returns:
            True if restored successfully, False otherwise (crash-safe)
        """
        try:
            key = f"table/{table_id}/header_state"
            state = self.get_bytes(key)
            if state:
                success = header.restoreState(QByteArray(state))
                if success:
                    logger.debug(f"Header state restored for '{table_id}'")
                else:
                    logger.warning(f"Failed to restore header state for '{table_id}'")
                return success
            return False
        except Exception as e:
            logger.error(f"Failed to restore header state for '{table_id}': {e}")
            return False
