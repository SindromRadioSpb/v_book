"""
WorkspaceManager - Professional workspace layout with collapsible sidebar.

Provides a QSplitter-based layout with:
- Collapsible sidebar with quick action buttons
- Main content area (QStackedWidget for navigation)
- Layout persistence (save/restore splitter state)
"""

import logging
from typing import Optional, Dict, Any

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QSplitter, QFrame, QStackedWidget, QLabel
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QIcon

logger = logging.getLogger(__name__)


class SidebarWidget(QFrame):
    """
    Collapsible sidebar with quick action buttons.

    Provides quick access to common workflows without menu navigation.
    """

    action_triggered = pyqtSignal(str)  # Emits action ID

    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumWidth(150)
        self.setMaximumWidth(250)

        self.init_ui()

    def init_ui(self):
        """Initialize sidebar UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # Header
        header = QLabel("<b>Quick Actions</b>")
        layout.addWidget(header)

        # Quick action buttons
        self.import_btn = QPushButton("Import Dictionary")
        self.import_btn.setToolTip("Import dictionary from CSV (Ctrl+Shift+I)")
        self.import_btn.clicked.connect(lambda: self.action_triggered.emit("tools.import_dictionary"))
        layout.addWidget(self.import_btn)

        self.tm_btn = QPushButton("Translation Memory")
        self.tm_btn.setToolTip("Manage translation memory (Ctrl+Shift+T)")
        self.tm_btn.clicked.connect(lambda: self.action_triggered.emit("premium.tm"))
        layout.addWidget(self.tm_btn)

        self.verify_btn = QPushButton("P1 Verification")
        self.verify_btn.setToolTip("Run P1 verification suite (Ctrl+Shift+V)")
        self.verify_btn.clicked.connect(lambda: self.action_triggered.emit("tools.verification"))
        layout.addWidget(self.verify_btn)

        # Spacer to push buttons to top
        layout.addStretch()

        logger.debug("Sidebar initialized")


class WorkspaceManager(QWidget):
    """
    Professional workspace layout manager.

    Structure:
      QSplitter (Horizontal)
        ├── SidebarWidget (collapsible, hidden by default)
        └── QStackedWidget (main navigation stack)

    Features:
    - Ctrl+B to toggle sidebar visibility
    - Save/restore layout (splitter state + sidebar visibility)
    - Version-controlled layout schema for migration
    """

    layout_changed = pyqtSignal()  # Emitted when layout changes (debounced)

    # Layout schema version for migration support
    LAYOUT_SCHEMA_VERSION = 1

    def __init__(self):
        super().__init__()

        # Create widgets
        self.sidebar = SidebarWidget()
        self.stack = QStackedWidget()

        # Splitter for resizable panels
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(self.stack)
        self.splitter.setCollapsible(0, True)  # Sidebar can collapse
        self.splitter.setCollapsible(1, False)  # Stack cannot collapse

        # Default: hide sidebar
        self.sidebar.hide()

        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)

        # Debounce timer for layout_changed signal (500ms)
        self._debounce_timer = QTimer()
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(500)
        self._debounce_timer.timeout.connect(self.layout_changed.emit)

        # Connect splitter moves to debounced signal
        self.splitter.splitterMoved.connect(self._on_splitter_moved)

        logger.debug("WorkspaceManager initialized")

    def _on_splitter_moved(self):
        """Handle splitter move (debounced)."""
        self._debounce_timer.start()

    def toggle_sidebar(self):
        """Toggle sidebar visibility (Ctrl+B)."""
        if self.sidebar.isVisible():
            self.sidebar.hide()
            logger.debug("Sidebar hidden")
        else:
            self.sidebar.show()
            logger.debug("Sidebar shown")

        # Emit layout changed immediately (not debounced) for toggle
        self.layout_changed.emit()

    def save_layout(self) -> Dict[str, Any]:
        """
        Serialize current layout state.

        Returns:
            dict: Layout data with schema version, sidebar visibility, splitter state
        """
        return {
            "layout_schema_version": self.LAYOUT_SCHEMA_VERSION,
            "sidebar_visible": self.sidebar.isVisible(),
            "splitter_state": bytes(self.splitter.saveState()).hex()
        }

    def restore_layout(self, data: Dict[str, Any]) -> bool:
        """
        Restore layout from serialized data.

        Args:
            data: Layout data dict

        Returns:
            bool: True if restored successfully, False on error (triggers fallback)
        """
        try:
            # Version check
            version = data.get("layout_schema_version")
            if version != self.LAYOUT_SCHEMA_VERSION:
                logger.warning(f"Layout schema version mismatch: got {version}, expected {self.LAYOUT_SCHEMA_VERSION}")
                return False

            # Restore sidebar visibility
            sidebar_visible = data.get("sidebar_visible", False)
            if sidebar_visible:
                self.sidebar.show()
            else:
                self.sidebar.hide()

            # Restore splitter state
            splitter_state_hex = data.get("splitter_state")
            if splitter_state_hex:
                splitter_state = bytes.fromhex(splitter_state_hex)
                success = self.splitter.restoreState(splitter_state)
                if not success:
                    logger.warning("Failed to restore splitter state")
                    return False

            logger.info("Layout restored successfully")
            return True

        except (KeyError, ValueError, TypeError) as e:
            logger.error(f"Failed to restore layout: {e}")
            return False

    def reset_to_default(self):
        """Reset layout to default state."""
        # Hide sidebar
        self.sidebar.hide()

        # Reset splitter to default proportions (200px sidebar, rest for stack)
        self.splitter.setSizes([200, 1000])

        logger.info("Layout reset to default")
