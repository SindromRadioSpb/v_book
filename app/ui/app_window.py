"""Main application window."""
import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import QDockWidget, QMainWindow, QStackedWidget, QMenuBar
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QShortcut, QKeySequence

from app.infra.settings import SettingsService
from app.services.audio_player_service import AudioPlayerService
from app.ui.workspace_manager import WorkspaceManager
from app.ui.command_palette import ActionsRegistry, ActionSpec, CommandPaletteDialog
from app.ui.project_dashboard import ProjectDashboard
from app.ui.project_view import ProjectView
from app.ui.verification_panel import VerificationPanel
from app.ui.translation_management_panel import TranslationManagementPanel
from app.ui.user_dictionaries_view import UserDictionariesView
from app.ui.coverage_panel import CoveragePanel
from app.ui.import_wizard import ImportWizard
from app.ui.widgets.audio_player_panel import AudioPlayerPanel

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
        # Shared internal audio player singleton.
        self.audio_player = AudioPlayerService.get_instance()

        # Central widget - workspace manager (create BEFORE menu bar)
        self.workspace = WorkspaceManager()
        self.setCentralWidget(self.workspace)

        # Mini player dock (hidden by default).
        self._init_audio_player_dock()

        # Alias for existing code (zero changes to navigation)
        self.stack = self.workspace.stack

        # Menu bar (now workspace exists)
        self.create_menu_bar()

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

        # Register actions for command palette
        self._register_actions()

        # Create Ctrl+P shortcut for command palette
        self.palette_shortcut = QShortcut(QKeySequence("Ctrl+P"), self)
        self.palette_shortcut.activated.connect(self._open_command_palette)

        # Global toggle for audio player dock.
        self.audio_panel_shortcut = QShortcut(QKeySequence("Ctrl+Alt+L"), self)
        self.audio_panel_shortcut.activated.connect(self.toggle_audio_player_panel)

        logger.info("AppWindow initialized")

    def _init_audio_player_dock(self):
        """Initialize Now Playing dock."""
        self.audio_player_dock = QDockWidget("Audio Player", self)
        self.audio_player_dock.setObjectName("audio_player_dock")
        self.audio_player_dock.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.audio_player_panel = AudioPlayerPanel(player=self.audio_player, parent=self.audio_player_dock)
        self.audio_player_dock.setWidget(self.audio_player_panel)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.audio_player_dock)

        is_visible = self.settings.get_bool("audio/playback/panel_visible", False)
        self.audio_player_dock.setVisible(is_visible)
        self.audio_player_dock.visibilityChanged.connect(
            lambda visible: self.settings.set_value("audio/playback/panel_visible", bool(visible))
        )

    def toggle_audio_player_panel(self):
        """Toggle Now Playing panel visibility."""
        self.audio_player_dock.setVisible(not self.audio_player_dock.isVisible())

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

        # Project Exchange (Export/Import bundles)
        tools_menu.addSeparator()
        export_bundle_action = QAction("&Export Project Bundle...", self)
        export_bundle_action.setShortcut("Ctrl+Shift+E")
        export_bundle_action.triggered.connect(self.export_project_bundle)
        tools_menu.addAction(export_bundle_action)

        import_bundle_action = QAction("I&mport Project Bundle...", self)
        import_bundle_action.setShortcut("Ctrl+Shift+B")
        import_bundle_action.triggered.connect(self.import_project_bundle)
        tools_menu.addAction(import_bundle_action)

        # Translation submenu
        tools_menu.addSeparator()
        translation_menu = tools_menu.addMenu("&Translation")

        # Translate Text
        translate_text_action = QAction("&Translate Text...", self)
        translate_text_action.setShortcut("Ctrl+Alt+T")
        translate_text_action.triggered.connect(self.open_translate_text_dialog)
        translation_menu.addAction(translate_text_action)

        # MT Provider Settings
        provider_settings_action = QAction("&MT Provider Settings...", self)
        provider_settings_action.setShortcut("Ctrl+Alt+P")
        provider_settings_action.triggered.connect(self.open_provider_settings)
        translation_menu.addAction(provider_settings_action)

        # Audio Provider Settings
        audio_provider_settings_action = QAction("&Audio Provider Settings...", self)
        audio_provider_settings_action.setShortcut("Ctrl+Alt+A")
        audio_provider_settings_action.triggered.connect(self.open_audio_provider_settings)
        translation_menu.addAction(audio_provider_settings_action)

        # Premium menu
        premium_menu = menubar.addMenu("&Premium")

        # Translation Management
        tm_action = QAction("&Translation Management", self)
        tm_action.setShortcut("Ctrl+Shift+T")
        tm_action.triggered.connect(self.open_translation_management)
        premium_menu.addAction(tm_action)

        # User Dictionaries
        user_dict_action = QAction("&User Dictionaries", self)
        user_dict_action.setShortcut("Ctrl+Shift+U")
        user_dict_action.triggered.connect(self.open_user_dictionaries)
        premium_menu.addAction(user_dict_action)

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

        toggle_audio_panel_action = QAction("Toggle &Audio Player", self)
        toggle_audio_panel_action.setShortcut("Ctrl+Alt+L")
        toggle_audio_panel_action.triggered.connect(self.toggle_audio_player_panel)
        view_menu.addAction(toggle_audio_panel_action)

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

    def _get_active_project_id(self) -> Optional[int]:
        """Best-effort active project context for workspace-level panels."""
        current = self.stack.currentWidget()
        if current is None:
            return None
        if hasattr(current, "project_id"):
            value = getattr(current, "project_id", None)
            if isinstance(value, int):
                return value
        return None

    def open_translation_management(self, project_id: Optional[int] = None):
        """Open translation management panel."""
        logger.info("Opening translation management panel")

        context_project_id = project_id if project_id is not None else self._get_active_project_id()

        # Create panel (uses context project scope when available).
        tm_panel = TranslationManagementPanel(project_id=context_project_id)
        tm_panel.back_requested.connect(self.back_to_dashboard)
        tm_panel.open_user_dictionaries_requested.connect(
            lambda pid=context_project_id: self.open_user_dictionaries(project_id=pid)
        )

        # Add to stack and show
        self.stack.addWidget(tm_panel)
        self.stack.setCurrentWidget(tm_panel)

    def open_user_dictionaries(self, project_id: Optional[int] = None):
        """Open User Dictionaries workspace."""
        logger.info("Opening user dictionaries workspace")

        context_project_id = project_id if project_id is not None else self._get_active_project_id()

        panel = UserDictionariesView(project_id=context_project_id, show_back_button=True)
        panel.back_requested.connect(self.back_to_dashboard)
        panel.open_translation_management_requested.connect(
            lambda pid=context_project_id: self.open_translation_management(project_id=pid)
        )
        self.stack.addWidget(panel)
        self.stack.setCurrentWidget(panel)

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

    def open_translate_text_dialog(self):
        """Open translate text dialog."""
        from app.ui.translate_text_dialog import show_translate_text_dialog

        logger.info("Opening translate text dialog")
        show_translate_text_dialog(parent=self)

    def open_provider_settings(self):
        """Open MT provider settings dialog."""
        from app.ui.provider_settings_dialog import show_provider_settings

        logger.info("Opening MT provider settings dialog")
        show_provider_settings(parent=self)

    def open_audio_provider_settings(self):
        """Open audio provider settings dialog."""
        from app.ui.audio_provider_settings_dialog import show_audio_provider_settings

        logger.info("Opening audio provider settings dialog")
        show_audio_provider_settings(parent=self)

    def open_project(self, project_id: int):
        """Open a project view."""
        logger.info(f"Opening project {project_id}")

        # Create project view
        project_view = ProjectView(project_id)
        project_view.back_to_dashboard.connect(self.back_to_dashboard)
        project_view.open_translation_management_requested.connect(self.open_translation_management)

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

    def _register_actions(self):
        """Register all application actions with the command palette."""
        registry = ActionsRegistry.get_instance()

        # Tools category
        registry.register(ActionSpec(
            action_id="tools.verification",
            title="Run P1 Verification",
            keywords=["verify", "p1", "test", "check"],
            shortcut="Ctrl+Shift+V",
            callback=self.open_verification,
            category="Tools"
        ))

        registry.register(ActionSpec(
            action_id="tools.import_dictionary",
            title="Import Dictionary",
            keywords=["import", "dict", "csv", "load"],
            shortcut="Ctrl+Shift+I",
            callback=self.open_import_wizard,
            category="Tools"
        ))

        # Premium category
        registry.register(ActionSpec(
            action_id="premium.tm",
            title="Translation Management",
            keywords=["tm", "translation", "memory", "manage"],
            shortcut="Ctrl+Shift+T",
            callback=self.open_translation_management,
            category="Premium"
        ))

        registry.register(ActionSpec(
            action_id="premium.user_dictionaries",
            title="User Dictionaries",
            keywords=["dictionary", "user", "deck", "study", "vocabulary"],
            shortcut="Ctrl+Shift+U",
            callback=self.open_user_dictionaries,
            category="Premium"
        ))

        registry.register(ActionSpec(
            action_id="tools.audio_provider_settings",
            title="Audio Provider Settings",
            keywords=["audio", "tts", "provider", "mms", "speech"],
            shortcut="Ctrl+Alt+A",
            callback=self.open_audio_provider_settings,
            category="Tools"
        ))

        registry.register(ActionSpec(
            action_id="premium.audio_player",
            title="Toggle Audio Player",
            keywords=["audio", "playback", "now playing", "queue", "dock"],
            shortcut="Ctrl+Alt+L",
            callback=self.toggle_audio_player_panel,
            category="Premium"
        ))

        registry.register(ActionSpec(
            action_id="premium.coverage",
            title="QA / Coverage",
            keywords=["qa", "coverage", "quality", "test"],
            shortcut="Ctrl+Shift+C",
            callback=self.open_coverage,
            category="Premium"
        ))

        # View category
        registry.register(ActionSpec(
            action_id="view.toggle_sidebar",
            title="Toggle Sidebar",
            keywords=["sidebar", "panel", "show", "hide"],
            shortcut="Ctrl+B",
            callback=self.workspace.toggle_sidebar,
            category="View"
        ))

        registry.register(ActionSpec(
            action_id="view.reset_layout",
            title="Reset Layout to Default",
            keywords=["reset", "layout", "default", "restore"],
            shortcut="Ctrl+Shift+R",
            callback=self.workspace.reset_to_default,
            category="View"
        ))

        # Navigate category
        registry.register(ActionSpec(
            action_id="navigate.dashboard",
            title="Projects",
            keywords=["dashboard", "home", "projects"],
            shortcut="",
            callback=self.back_to_dashboard,
            category="Navigate"
        ))

        logger.info(f"Registered {len(registry.get_all())} actions")

    def _open_command_palette(self):
        """Open command palette dialog."""
        dialog = CommandPaletteDialog(self)
        dialog.action_selected.connect(self._execute_palette_action)
        dialog.exec()

    def _execute_palette_action(self, action_id: str):
        """Execute action from command palette."""
        registry = ActionsRegistry.get_instance()
        success = registry.execute(action_id)
        if not success:
            logger.warning(f"Failed to execute action: {action_id}")

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
            "workspace.projects": self.back_to_dashboard,
            "workspace.tm": self.open_translation_management,
            "workspace.user_dictionaries": self.open_user_dictionaries,
            "navigate.dashboard": self.back_to_dashboard,
            "tools.verification": self.open_verification,
            "tools.import_dictionary": self.open_import_wizard,
            "premium.tm": self.open_translation_management,
            "premium.coverage": self.open_coverage,
        }

        handler = action_map.get(action_id)
        if handler:
            handler()
        else:
            logger.warning(f"Unknown sidebar action: {action_id}")

    def export_project_bundle(self):
        """Export current project as .hdleproj bundle."""
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        from pathlib import Path
        from app.services.project_exchange.worker import ProjectExportWorker
        from app.services.project_exchange.dto import ExportOptions
        from app.ui.dialogs.project_exchange_dialogs import ExportProgressDialog

        # Get current project_id from active view
        current = self.stack.currentWidget()
        if not hasattr(current, "project_id") or current.project_id is None:
            QMessageBox.information(
                self,
                "Project Required",
                "Please open a project first to export it as a bundle."
            )
            return

        project_id = current.project_id

        # File dialog
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Project Bundle",
            "",
            "HDLE Project Bundle (*.hdleproj)"
        )

        if not path:
            return

        # Ensure .hdleproj extension
        path = Path(path)
        if path.suffix != ".hdleproj":
            path = path.with_suffix(".hdleproj")

        # Create worker
        options = ExportOptions(include_snapshots=True)
        worker = ProjectExportWorker(project_id, path, options)

        # Create progress dialog
        progress_dialog = ExportProgressDialog(self)

        # Connect signals
        worker.progress.connect(progress_dialog.update_progress)
        worker.finished.connect(lambda report: progress_dialog.set_completed(report))
        worker.error.connect(lambda error: self._on_export_error(error, progress_dialog))
        progress_dialog.cancel_requested.connect(worker.cancel)

        # Store worker reference to prevent GC
        self._export_worker = worker

        # Start
        worker.start()
        progress_dialog.exec()

    def _on_export_error(self, error: str, dialog):
        """Handle export error."""
        from PyQt6.QtWidgets import QMessageBox
        from app.services.project_exchange.dto import ExportReport

        fake_report = ExportReport(success=False, error_message=error)
        dialog.set_completed(fake_report)

    def import_project_bundle(self):
        """Import .hdleproj bundle."""
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        from pathlib import Path
        from app.services.project_exchange import bundle_format
        from app.services.project_exchange.worker import ProjectImportWorker
        from app.services.project_exchange.dto import ImportOptions
        from app.ui.dialogs.project_exchange_dialogs import (
            ImportPreviewDialog,
            ImportProgressDialog,
        )

        # File dialog
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Project Bundle",
            "",
            "HDLE Project Bundle (*.hdleproj)"
        )

        if not path:
            return

        bundle_path = Path(path)

        # Peek manifest for preview
        try:
            manifest = bundle_format.peek_manifest(bundle_path)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Invalid Bundle",
                f"Failed to read bundle:\n\n{e}"
            )
            return

        # Show preview dialog
        preview_dialog = ImportPreviewDialog(manifest, self)
        if preview_dialog.exec() != ImportPreviewDialog.DialogCode.Accepted:
            return

        # Get custom name
        custom_name = preview_dialog.get_custom_name()

        # Create worker
        options = ImportOptions(
            rename_if_conflict=True,
            custom_name=custom_name if custom_name != manifest.project_name else None
        )
        worker = ProjectImportWorker(bundle_path, options)

        # Create progress dialog
        progress_dialog = ImportProgressDialog(self)

        # Connect signals
        worker.progress.connect(progress_dialog.update_progress)
        worker.finished.connect(lambda report: self._on_import_finished(report, progress_dialog))
        worker.error.connect(lambda error: self._on_import_error(error, progress_dialog))
        progress_dialog.cancel_requested.connect(worker.cancel)

        # Store worker reference to prevent GC
        self._import_worker = worker

        # Start
        worker.start()
        progress_dialog.exec()

    def _on_import_finished(self, report, dialog):
        """Handle successful import."""
        dialog.set_completed(report)

        # Refresh dashboard (if visible)
        if hasattr(self, "dashboard") and isinstance(self.stack.currentWidget(), type(self.dashboard)):
            self.dashboard.load_projects()

    def _on_import_error(self, error: str, dialog):
        """Handle import error."""
        from app.services.project_exchange.dto import ImportReport

        fake_report = ImportReport(success=False, error_message=error)
        dialog.set_completed(fake_report)

    def closeEvent(self, event):
        """Handle window close."""
        logger.info("Application closing")

        # Save window geometry and workspace layout
        self.settings.save_window_geometry(self)
        self._save_workspace_layout()
        self.settings.sync()

        event.accept()
