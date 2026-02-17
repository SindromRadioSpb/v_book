"""
WorkspaceManager - Professional workspace layout with collapsible sidebar.

Provides a QSplitter-based layout with:
- Collapsible sidebar with primary navigation
- Main content area (QStackedWidget for navigation)
- Layout persistence (save/restore splitter state)
"""

import logging
from typing import Dict, Any

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QPushButton,
    QSplitter,
    QFrame,
    QStackedWidget,
    QLabel,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer

logger = logging.getLogger(__name__)


class SidebarWidget(QFrame):
    """Collapsible sidebar with workspace and tool actions."""

    action_triggered = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumWidth(170)
        self.setMaximumWidth(280)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        header = QLabel("<b>Workspace</b>")
        layout.addWidget(header)

        nav_label = QLabel("<i>Primary Navigation</i>")
        nav_label.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(nav_label)

        self.projects_btn = QPushButton("Projects")
        self.projects_btn.setToolTip("Open Projects dashboard")
        self.projects_btn.clicked.connect(lambda: self.action_triggered.emit("workspace.projects"))
        layout.addWidget(self.projects_btn)

        # Backward-compatible alias for older tests/callers.
        self.dashboard_btn = self.projects_btn

        self.tm_btn = QPushButton("Translation Management")
        self.tm_btn.setToolTip("Open Translation Management (Ctrl+Shift+T)")
        self.tm_btn.clicked.connect(lambda: self.action_triggered.emit("workspace.tm"))
        layout.addWidget(self.tm_btn)

        self.user_dict_btn = QPushButton("User Dictionaries")
        self.user_dict_btn.setToolTip("Open User Dictionaries (Ctrl+Shift+U)")
        self.user_dict_btn.clicked.connect(lambda: self.action_triggered.emit("workspace.user_dictionaries"))
        layout.addWidget(self.user_dict_btn)

        layout.addSpacing(8)
        tools_label = QLabel("<i>Tools</i>")
        tools_label.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(tools_label)

        self.import_btn = QPushButton("Import Dictionary")
        self.import_btn.setToolTip("Import dictionary from CSV (Ctrl+Shift+I)")
        self.import_btn.clicked.connect(lambda: self.action_triggered.emit("tools.import_dictionary"))
        layout.addWidget(self.import_btn)

        self.coverage_btn = QPushButton("QA / Coverage")
        self.coverage_btn.setToolTip("Open QA/Coverage (Ctrl+Shift+C)")
        self.coverage_btn.clicked.connect(lambda: self.action_triggered.emit("premium.coverage"))
        layout.addWidget(self.coverage_btn)

        self.verify_btn = QPushButton("P1 Verification")
        self.verify_btn.setToolTip("Run P1 verification suite (Ctrl+Shift+V)")
        self.verify_btn.clicked.connect(lambda: self.action_triggered.emit("tools.verification"))
        layout.addWidget(self.verify_btn)

        layout.addStretch()
        logger.debug("Sidebar initialized")


class WorkspaceManager(QWidget):
    """Professional workspace layout manager."""

    layout_changed = pyqtSignal()

    # v2: Sidebar switched to primary workspace navigation.
    LAYOUT_SCHEMA_VERSION = 2

    def __init__(self):
        super().__init__()

        self.sidebar = SidebarWidget()
        self.stack = QStackedWidget()

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(self.stack)
        self.splitter.setCollapsible(0, True)
        self.splitter.setCollapsible(1, False)

        self.sidebar.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)

        self._debounce_timer = QTimer()
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(500)
        self._debounce_timer.timeout.connect(self.layout_changed.emit)

        self.splitter.splitterMoved.connect(self._on_splitter_moved)

        logger.debug("WorkspaceManager initialized")

    def _on_splitter_moved(self):
        self._debounce_timer.start()

    def toggle_sidebar(self):
        if self.sidebar.isVisible():
            self.sidebar.hide()
            logger.debug("Sidebar hidden")
        else:
            self.sidebar.show()
            logger.debug("Sidebar shown")

        self.layout_changed.emit()

    def save_layout(self) -> Dict[str, Any]:
        return {
            "layout_schema_version": self.LAYOUT_SCHEMA_VERSION,
            "sidebar_visible": self.sidebar.isVisible(),
            "splitter_state": bytes(self.splitter.saveState()).hex(),
        }

    def restore_layout(self, data: Dict[str, Any]) -> bool:
        try:
            version = data.get("layout_schema_version")
            if version != self.LAYOUT_SCHEMA_VERSION:
                logger.warning(
                    "Layout schema version mismatch: got %s, expected %s",
                    version,
                    self.LAYOUT_SCHEMA_VERSION,
                )
                return False

            if "sidebar_visible" not in data or "splitter_state" not in data:
                logger.warning("Layout data missing required keys")
                return False

            if data.get("sidebar_visible", False):
                self.sidebar.show()
            else:
                self.sidebar.hide()

            splitter_state_hex = data.get("splitter_state")
            if splitter_state_hex:
                splitter_state = bytes.fromhex(splitter_state_hex)
                if not self.splitter.restoreState(splitter_state):
                    logger.warning("Failed to restore splitter state")
                    return False

            logger.info("Layout restored successfully")
            return True
        except (KeyError, ValueError, TypeError) as e:
            logger.error("Failed to restore layout: %s", e)
            return False

    def reset_to_default(self):
        self.sidebar.hide()
        self.splitter.setSizes([220, 980])
        logger.info("Layout reset to default")
