"""Main application window."""
import logging
from pathlib import Path

from PyQt6.QtWidgets import QMainWindow, QStackedWidget
from PyQt6.QtCore import Qt

from app.ui.project_dashboard import ProjectDashboard
from app.ui.project_view import ProjectView

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
        # Central widget - stack for switching views
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        # Create dashboard
        self.dashboard = ProjectDashboard()
        self.dashboard.project_selected.connect(self.open_project)
        self.stack.addWidget(self.dashboard)

        # Show dashboard initially
        self.stack.setCurrentWidget(self.dashboard)

        logger.info("AppWindow initialized")

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
