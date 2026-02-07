"""Main application window."""
import logging
from pathlib import Path

from PyQt6.QtWidgets import QMainWindow, QStackedWidget, QMenuBar
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction

from app.infra.settings import SettingsService
from app.ui.workspace_manager import WorkspaceManager
from app.ui.project_dashboard import ProjectDashboard
from app.ui.project_view import ProjectView
from app.ui.verification_panel import VerificationPanel
from app.ui.translation_management_panel import TranslationManagementPanel
from app.ui.coverage_panel import CoveragePanel
from app.ui.import_wizard import ImportWizard

logger = logging.getLogger(__name__)


class AppWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("HDLE Premium - Hebraic Dynamic Lexicon Engine")
        self.setMinimumSize(1200, 800)

        # Get settings service
        self.settings = SettingsService.get_instance()

        self.init_ui()

        # Restore window geometry
        self.settings.restore_window_geometry(self)

    def init_ui(self):
        """Initialize the UI."""
        # Menu bar
        self.create_menu_bar()

        # Central widget - workspace manager (contains stack)
        self.workspace = WorkspaceManager()
        self.setCentralWidget(self.workspace)

        # Alias for existing code (zero changes to navigation)
        self.stack = self.workspace.stack

        # Connect sidebar actions
        self.workspace.sidebar.action_triggered.connect(self._on_sidebar_action)

        # Connect layout changes to autosave (debounced)
        self.workspace.layout_changed.connect(self._save_workspace_layout)

        # Create dashboard
        self.dashboard = ProjectDashboard()
        self.dashboard.project_selected.connect(self.open_project)
        self.dashboard.verification_requested.connect(self.open_verification)
        self.stack.addWidget(self.dashboard)

        # Show dashboard initially
        self.stack.setCurrentWidget(self.dashboard)

        # Restore workspace layout
        self._restore_workspace_layout()

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

        # Import Dictionary
        import_action = QAction("&Import Dictionary...", self)
        import_action.setShortcut("Ctrl+Shift+I")
        import_action.triggered.connect(self.open_import_wizard)
        tools_menu.addAction(import_action)

        # Premium menu
        premium_menu = menubar.addMenu("&Premium")

        # Translation Management
        tm_action = QAction("&Translation Management", self)
        tm_action.setShortcut("Ctrl+Shift+T")
        tm_action.triggered.connect(self.open_translation_management)
        premium_menu.addAction(tm_action)

        # QA/Coverage (requires project context)
        coverage_action = QAction("&QA / Coverage", self)
        coverage_action.setShortcut("Ctrl+Shift+C")
        coverage_action.triggered.connect(self.open_coverage)
        premium_menu.addAction(coverage_action)

        # View menu
        view_menu = menubar.addMenu("&View")

        # Toggle Sidebar
        toggle_sidebar_action = QAction("Toggle &Sidebar", self)
        toggle_sidebar_action.setShortcut("Ctrl+B")
        toggle_sidebar_action.triggered.connect(self.workspace.toggle_sidebar)
        view_menu.addAction(toggle_sidebar_action)

        # Reset Layout
        reset_layout_action = QAction("&Reset Layout to Default", self)
        reset_layout_action.setShortcut("Ctrl+Shift+R")
        reset_layout_action.triggered.connect(self.workspace.reset_to_default)
        view_menu.addAction(reset_layout_action)

    def open_verification(self):
        """Open verification panel."""
        logger.info("Opening verification panel")

        # Create verification panel
        verification_panel = VerificationPanel()
        verification_panel.back_requested.connect(self.back_to_dashboard)

        # Add to stack and show
        self.stack.addWidget(verification_panel)
        self.stack.setCurrentWidget(verification_panel)

    def open_import_wizard(self):
        """Open import wizard."""
        logger.info("Opening import wizard")

        # Create import wizard
        import_wizard = ImportWizard()
        import_wizard.back_requested.connect(self.back_to_dashboard)

        # Add to stack and show
        self.stack.addWidget(import_wizard)
        self.stack.setCurrentWidget(import_wizard)

    def open_translation_management(self):
        """Open translation management panel."""
        logger.info("Opening translation management panel")

        # Create panel (global TM by default)
        tm_panel = TranslationManagementPanel(project_id=None)
        tm_panel.back_requested.connect(self.back_to_dashboard)

        # Add to stack and show
        self.stack.addWidget(tm_panel)
        self.stack.setCurrentWidget(tm_panel)

    def open_coverage(self):
        """Open coverage panel."""
        from PyQt6.QtWidgets import QMessageBox

        # Coverage requires project context
        # Check if we're in a project view
        current_widget = self.stack.currentWidget()
        project_id = None

        if hasattr(current_widget, 'project_id'):
            project_id = current_widget.project_id

        if project_id is None:
            QMessageBox.information(
                self,
                "Project Required",
                "QA/Coverage requires a project context.\n\n"
                "Please open a project first, then access Premium → QA/Coverage."
            )
            return

        logger.info(f"Opening coverage panel for project {project_id}")

        # Create panel
        coverage_panel = CoveragePanel(project_id)
        coverage_panel.back_requested.connect(self.back_to_dashboard)

        # Add to stack and show
        self.stack.addWidget(coverage_panel)
        self.stack.setCurrentWidget(coverage_panel)

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

    def _save_workspace_layout(self):
        """Save workspace layout to settings."""
        try:
            layout = self.workspace.save_layout()
            self.settings.set_json("workspace/layout", layout)
            logger.debug("Workspace layout saved")
        except Exception as e:
            logger.error(f"Failed to save workspace layout: {e}")

    def _restore_workspace_layout(self):
        """Restore workspace layout from settings."""
        try:
            layout = self.settings.get_json("workspace/layout")
            if layout:
                success = self.workspace.restore_layout(layout)
                if not success:
                    logger.warning("Failed to restore layout, resetting to default")
                    self.workspace.reset_to_default()
            else:
                logger.debug("No saved layout found, using default")
        except Exception as e:
            logger.error(f"Failed to restore workspace layout: {e}, resetting to default")
            self.workspace.reset_to_default()

    def _on_sidebar_action(self, action_id: str):
        """Route sidebar action to appropriate handler."""
        action_map = {
            "tools.verification": self.open_verification,
            "tools.import_dictionary": self.open_import_wizard,
            "premium.tm": self.open_translation_management,
        }

        handler = action_map.get(action_id)
        if handler:
            handler()
        else:
            logger.warning(f"Unknown sidebar action: {action_id}")

    def closeEvent(self, event):
        """Handle window close."""
        logger.info("Application closing")

        # Save window geometry and workspace layout
        self.settings.save_window_geometry(self)
        self._save_workspace_layout()
        self.settings.sync()

        event.accept()
