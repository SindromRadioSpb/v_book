"""Main application window."""
import logging
from pathlib import Path

from PyQt6.QtWidgets import QMainWindow, QStackedWidget, QMenuBar
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction

from app.ui.project_dashboard import ProjectDashboard
from app.ui.project_view import ProjectView
from app.ui.verification_panel import VerificationPanel

logger = logging.getLogger(__name__)


class AppWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("HDLE Premium - Hebraic Dynamic Lexicon Engine")
        self.setMinimumSize(1200, 800)

        self.init_ui()

    def init_ui(self):
        """Initialize the UI."""
        # Menu bar
        self.create_menu_bar()

        # Central widget - stack for switching views
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        # Create dashboard
        self.dashboard = ProjectDashboard()
        self.dashboard.project_selected.connect(self.open_project)
        self.dashboard.verification_requested.connect(self.open_verification)
        self.stack.addWidget(self.dashboard)

        # Show dashboard initially
        self.stack.setCurrentWidget(self.dashboard)

        logger.info("AppWindow initialized")

    def create_menu_bar(self):
        """Create menu bar."""
        menubar = self.menuBar()

        # Tools menu
        tools_menu = menubar.addMenu("&Tools")

        # Verification action
        verification_action = QAction("&Verification (P1 Scenario 7)", self)
        verification_action.setShortcut("Ctrl+Shift+V")
        verification_action.triggered.connect(self.open_verification)
        tools_menu.addAction(verification_action)

    def open_verification(self):
        """Open verification panel."""
        logger.info("Opening verification panel")

        # Create verification panel
        verification_panel = VerificationPanel()
        verification_panel.back_requested.connect(self.back_to_dashboard)

        # Add to stack and show
        self.stack.addWidget(verification_panel)
        self.stack.setCurrentWidget(verification_panel)

    def open_project(self, project_id: int):
        """Open a project view."""
        logger.info(f"Opening project {project_id}")

        # Create project view
        project_view = ProjectView(project_id)
        project_view.back_to_dashboard.connect(self.back_to_dashboard)

        # Add to stack and show
        self.stack.addWidget(project_view)
        self.stack.setCurrentWidget(project_view)

    def back_to_dashboard(self):
        """Return to dashboard."""
        logger.info("Returning to dashboard")

        # Remove current project view
        current = self.stack.currentWidget()
        if current != self.dashboard:
            self.stack.removeWidget(current)
            current.deleteLater()

        # Show dashboard and refresh
        self.stack.setCurrentWidget(self.dashboard)
        self.dashboard.load_projects()

    def closeEvent(self, event):
        """Handle window close."""
        logger.info("Application closing")
        event.accept()
