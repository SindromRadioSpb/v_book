"""Main application window."""
import logging
from pathlib import Path
from time import monotonic
from typing import Dict, List, Optional, Set

from PyQt6.QtWidgets import QDockWidget, QMainWindow, QStackedWidget, QMenuBar
from PyQt6.QtCore import Qt, QTimer
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
from app.services.project_service import ProjectService

logger = logging.getLogger(__name__)


class AppWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("HDLE Premium - Hebraic Dynamic Lexicon Engine")
        self.setMinimumSize(1200, 800)

        # Get settings service
        self.settings = SettingsService.get_instance()
        self.project_service = ProjectService()

        # Workspace identity/lifecycle registry.
        self._workspace_instances: Dict[str, object] = {}
        self._project_instances: Dict[int, ProjectView] = {}

        # Current project source-of-truth.
        self.current_project_id: Optional[int] = None
        self.current_project_name: str = ""
        self._recent_project_ids: List[int] = []
        self._pending_project_tab: Optional[str] = None
        self._workspace_history: List[str] = []
        self._badge_error_logged_at_ms: int = 0

        self.init_ui()

        # Restore window geometry
        self.settings.restore_window_geometry(self)

    def _show_nav_status(self, message: str, timeout_ms: int = 3500) -> None:
        text = str(message or "").strip()
        if not text:
            return
        self.statusBar().showMessage(text, timeout_ms)

    def _is_widget_in_stack(self, widget: object) -> bool:
        if widget is None:
            return False
        for i in range(self.stack.count()):
            if self.stack.widget(i) is widget:
                return True
        return False

    def _normalize_optional_project_id(self, project_id: Optional[int]) -> Optional[int]:
        if isinstance(project_id, bool):
            return None
        if project_id is None:
            return None
        try:
            return int(project_id)
        except (TypeError, ValueError):
            return None

    def _current_workspace_key(self) -> str:
        return str(self.workspace.sidebar.active_workspace or "workspace.projects")

    def _set_active_workspace(self, workspace_key: str, *, push_history: bool = True) -> None:
        current_key = self._current_workspace_key()
        target_key = str(workspace_key or "workspace.projects")
        if push_history and current_key != target_key:
            self._workspace_history.append(current_key)
            if len(self._workspace_history) > 32:
                self._workspace_history = self._workspace_history[-32:]
        self.workspace.set_active_workspace(target_key)
        self.settings.set_value("workspace/active_workspace", target_key)

    def _navigate_workspace_back(self) -> None:
        while self._workspace_history:
            prev_key = self._workspace_history.pop()
            if prev_key == "workspace.tm":
                self.open_translation_management(push_history=False)
                self._show_nav_status("Returned to Translation Management.")
                return
            if prev_key == "workspace.user_dictionaries":
                self.open_user_dictionaries(push_history=False)
                self._show_nav_status("Returned to User Dictionaries.")
                return
            if prev_key == "workspace.audio":
                self.open_audio_workspace(push_history=False)
                self._show_nav_status("Returned to Audio Player.")
                return
            if prev_key == "workspace.projects":
                self.back_to_dashboard(push_history=False)
                return
        self.back_to_dashboard(push_history=False)

    def _register_workspace_instance(self, key: str, widget: object) -> None:
        self._workspace_instances[key] = widget

    def _unregister_workspace_instance(self, key: str) -> None:
        self._workspace_instances.pop(key, None)

    def _resolve_workspace_instance(self, key: str):
        widget = self._workspace_instances.get(key)
        if widget is None:
            return None
        if self._is_widget_in_stack(widget):
            return widget
        self._workspace_instances.pop(key, None)
        return None

    def _remove_widget_from_stack(self, widget: object) -> None:
        if widget is None:
            return
        if self._is_widget_in_stack(widget):
            self.stack.removeWidget(widget)  # type: ignore[arg-type]
        try:
            widget.deleteLater()  # type: ignore[union-attr]
        except Exception:
            pass

    def _is_valid_project_id(self, project_id: Optional[int]) -> bool:
        if project_id is None:
            return False
        try:
            pid = int(project_id)
        except (TypeError, ValueError):
            return False
        try:
            with self.project_service.db_service.get_session() as session:
                return self.project_service.get_project(session, pid) is not None
        except Exception:
            return False

    def _lookup_project_name(self, project_id: Optional[int]) -> str:
        if project_id is None:
            return ""
        try:
            pid = int(project_id)
        except (TypeError, ValueError):
            return ""
        try:
            with self.project_service.db_service.get_session() as session:
                project = self.project_service.get_project(session, pid)
            if project is None:
                return ""
            return str(getattr(project, "name", "") or "").strip()
        except Exception:
            return ""

    def _save_current_project_context(self) -> None:
        if self.current_project_id is None:
            self.settings.remove("workspace/current_project_id")
            self.settings.remove("workspace/current_project_name")
            return
        self.settings.set_value("workspace/current_project_id", int(self.current_project_id))
        self.settings.set_value("workspace/current_project_name", self.current_project_name)

    def _set_current_project_context(self, project_id: Optional[int], project_name: Optional[str] = None) -> None:
        if project_id is not None and not self._is_valid_project_id(project_id):
            project_id = None
            project_name = ""

        if project_id is None:
            self.current_project_id = None
            self.current_project_name = ""
            self.workspace.sidebar.set_current_project(None, "", "All projects")
            self._save_current_project_context()
            return

        self.current_project_id = int(project_id)
        resolved_name = str(project_name or "").strip() or self._lookup_project_name(self.current_project_id)
        self.current_project_name = resolved_name
        self.workspace.sidebar.set_current_project(
            self.current_project_id,
            self.current_project_name,
            "Current Project",
        )
        self._save_current_project_context()

    def _restore_current_project_context(self) -> None:
        raw_pid = self.settings.get_int("workspace/current_project_id", 0)
        restored_pid = raw_pid if raw_pid > 0 else None
        restored_name = self.settings.get_string("workspace/current_project_name", "")
        self._set_current_project_context(restored_pid, restored_name)

    def _load_recent_project_ids(self) -> None:
        saved = self.settings.get_json("workspace/recent_project_ids", [])
        if not isinstance(saved, list):
            self._recent_project_ids = []
        else:
            parsed: List[int] = []
            seen: Set[int] = set()
            for value in saved:
                try:
                    pid = int(value)
                except (TypeError, ValueError):
                    continue
                if pid <= 0 or pid in seen:
                    continue
                seen.add(pid)
                parsed.append(pid)
            self._recent_project_ids = parsed[:12]
        self.workspace.sidebar.set_recent_project_ids(self._recent_project_ids)

    def _push_recent_project(self, project_id: int) -> None:
        pid = int(project_id)
        new_list = [pid]
        for value in self._recent_project_ids:
            if value != pid:
                new_list.append(value)
        self._recent_project_ids = new_list[:12]
        self.settings.set_json("workspace/recent_project_ids", self._recent_project_ids)
        self.workspace.sidebar.set_recent_project_ids(self._recent_project_ids)

    def _on_projects_catalog_loaded(self, projects: list) -> None:
        self.workspace.sidebar.set_project_catalog(projects, self._recent_project_ids)
        if self.current_project_id is None:
            return
        if not self._is_valid_project_id(self.current_project_id):
            self._set_current_project_context(None, "")
            return
        if not self.current_project_name:
            self._set_current_project_context(self.current_project_id, self._lookup_project_name(self.current_project_id))

    def _focus_or_create_workspace_widget(self, key: str, factory):
        widget = self._resolve_workspace_instance(key)
        if widget is None:
            widget = factory()
            self.stack.addWidget(widget)
            self._register_workspace_instance(key, widget)
        self.stack.setCurrentWidget(widget)
        return widget

    def _open_current_project(self) -> None:
        if self.current_project_id is None:
            self.back_to_dashboard()
            self._show_nav_status("Select a project to set Current Project.")
            return
        self.open_project(self.current_project_id)

    def _open_current_project_tab(self, tab_key: str) -> None:
        if self.current_project_id is None:
            self._pending_project_tab = str(tab_key or "").strip().lower() or None
            self.back_to_dashboard(push_history=False)
            self._show_nav_status("Open a project to continue. Target tab is queued.")
            return
        project_view = self._open_or_focus_project(self.current_project_id)
        if project_view is None:
            self._show_nav_status("Failed to open current project.")
            return
        if not project_view.focus_tab(tab_key):
            self._show_nav_status(f"Tab '{tab_key}' is unavailable for current project.")
            return
        self._set_active_workspace("workspace.projects")
        self._show_nav_status(f"Opened {tab_key.replace('_', ' ').title()} in current project.")

    def _on_workspace_sidebar_open_project(self, action_id: str) -> bool:
        prefix = "workspace.open_project:"
        if not action_id.startswith(prefix):
            return False
        raw = action_id[len(prefix):]
        try:
            project_id = int(raw)
        except (TypeError, ValueError):
            self._show_nav_status("Invalid project selection.")
            return True
        self.open_project(project_id)
        return True

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

        # Debounced cross-view refresh queue (used for Audio Player edit/generate actions).
        self._pending_refresh_fields: Set[str] = set()
        self._pending_refresh_project_ids: Set[int] = set()
        self._pending_refresh_all_projects: bool = False
        self._cross_refresh_timer = QTimer(self)
        self._cross_refresh_timer.setSingleShot(True)
        self._cross_refresh_timer.setInterval(250)
        self._cross_refresh_timer.timeout.connect(self._flush_cross_view_refresh)

        # Menu bar (now workspace exists)
        self.create_menu_bar()

        # Connect sidebar actions
        self.workspace.sidebar.action_triggered.connect(self._on_sidebar_action)
        self.workspace.sidebar.section_state_changed.connect(self._save_sidebar_sections_state)

        # Connect layout changes to autosave (debounced)
        self.workspace.layout_changed.connect(self._save_workspace_layout)

        # Create dashboard
        self.dashboard = ProjectDashboard()
        self.dashboard.project_selected.connect(self.open_project)
        self.dashboard.verification_requested.connect(self.open_verification)
        self.dashboard.projects_loaded.connect(self._on_projects_catalog_loaded)
        self.stack.addWidget(self.dashboard)
        self._register_workspace_instance("workspace.projects", self.dashboard)

        # Show dashboard initially
        self.stack.setCurrentWidget(self.dashboard)

        self._load_recent_project_ids()
        self._restore_current_project_context()
        self._restore_sidebar_sections_state()

        # Restore workspace layout
        self._restore_workspace_layout()
        self._restore_active_workspace()

        # Register actions for command palette
        self._register_actions()

        # Create Ctrl+P shortcut for command palette
        self.palette_shortcut = QShortcut(QKeySequence("Ctrl+P"), self)
        self.palette_shortcut.activated.connect(self._open_command_palette)

        # Optional async badges refresh (non-blocking, low frequency).
        self._workspace_badges_timer = QTimer(self)
        self._workspace_badges_timer.setInterval(45000)
        self._workspace_badges_timer.timeout.connect(self._refresh_workspace_badges)
        self._workspace_badges_timer.start()
        self._refresh_workspace_badges()
        self._validate_shortcut_conflicts()

        logger.info("AppWindow initialized")

    def _init_audio_player_dock(self):
        """Initialize Now Playing dock."""
        self.audio_player_dock = QDockWidget("Audio Player", self)
        self.audio_player_dock.setObjectName("audio_player_dock")
        self.audio_player_dock.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.audio_player_panel = AudioPlayerPanel(player=self.audio_player, parent=self.audio_player_dock)
        self.audio_player_panel.go_to_source_requested.connect(self._on_audio_go_to_source_requested)
        self.audio_player_panel.data_changed.connect(self._on_audio_player_data_changed)
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

    def open_audio_workspace(self, push_history: bool = True):
        """Focus/open Audio Player dock as a primary workspace target."""
        self.audio_player_dock.show()
        self.audio_player_dock.raise_()
        self.audio_player_panel.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        self._set_active_workspace("workspace.audio", push_history=push_history)
        self._show_nav_status("Audio Player opened.")

    def _restore_active_workspace(self) -> None:
        """Restore active workspace widget/focus from persisted state."""
        self._workspace_history.clear()
        active_workspace = self.settings.get_string("workspace/active_workspace", "workspace.projects")
        key = str(active_workspace or "workspace.projects")
        if key == "workspace.ud":
            key = "workspace.user_dictionaries"
        if key == "workspace.tm":
            self.open_translation_management(push_history=False)
            return
        if key == "workspace.user_dictionaries":
            self.open_user_dictionaries(push_history=False)
            return
        if key == "workspace.audio":
            self.open_audio_workspace(push_history=False)
            return
        self.back_to_dashboard(push_history=False)

    def _refresh_workspace_badges(self):
        """Best-effort lightweight badges refresh (no blocking DB calls)."""
        try:
            queue_count = len(self.audio_player.queue_snapshot())
        except Exception as exc:
            queue_count = -1
            self._log_badge_refresh_warning("audio", exc)

        tm_count = None
        tm_widget = self._resolve_workspace_instance("workspace.tm")
        if isinstance(tm_widget, TranslationManagementPanel):
            try:
                tm_count = int(getattr(tm_widget, "total_count", 0))
            except Exception as exc:
                tm_count = -1
                self._log_badge_refresh_warning("tm", exc)

        ud_due_count = None
        ud_widget = self._resolve_workspace_instance("workspace.user_dictionaries")
        if isinstance(ud_widget, UserDictionariesView):
            try:
                ud_due_count = int(len(getattr(ud_widget, "_review_cards", []) or []))
            except Exception as exc:
                ud_due_count = -1
                self._log_badge_refresh_warning("user_dictionaries", exc)

        self.workspace.sidebar.update_badges(
            queue_count=queue_count,
            tm_filtered_count=tm_count,
            ud_due_count=ud_due_count,
        )

    def _collect_shortcut_conflicts(self) -> Dict[str, List[str]]:
        by_shortcut: Dict[str, List[str]] = {}

        def _add(shortcut_text: str, source: str) -> None:
            key = str(shortcut_text or "").strip().upper()
            if not key:
                return
            by_shortcut.setdefault(key, []).append(source)

        for action in self.findChildren(QAction):
            seq = action.shortcut().toString(QKeySequence.SequenceFormat.PortableText)
            if not seq:
                continue
            source = f"QAction:{action.text().strip() or action.objectName() or '<unnamed>'}"
            _add(seq, source)

        for shortcut in self.findChildren(QShortcut):
            seq = shortcut.key().toString(QKeySequence.SequenceFormat.PortableText)
            if not seq:
                continue
            parent_name = shortcut.parent().objectName() if shortcut.parent() is not None else ""
            source = f"QShortcut:{parent_name or '<window>'}"
            _add(seq, source)

        return {k: v for k, v in by_shortcut.items() if len(v) > 1}

    def _validate_shortcut_conflicts(self) -> None:
        conflicts = self._collect_shortcut_conflicts()
        if not conflicts:
            logger.info("Shortcut conflict check: no duplicates found")
            return
        for shortcut_text, sources in conflicts.items():
            logger.warning("Shortcut conflict detected: %s used by %s", shortcut_text, ", ".join(sources))

    def _log_badge_refresh_warning(self, area: str, exc: Exception) -> None:
        now_stamp = int(monotonic() * 1000)
        if (now_stamp - self._badge_error_logged_at_ms) < 60000:
            return
        self._badge_error_logged_at_ms = now_stamp
        logger.warning("Workspace badge refresh failed (%s): %s", area, exc)

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

        pronunciation_bootstrap_action = QAction("&Pronunciation Bootstrap...", self)
        pronunciation_bootstrap_action.setShortcut("Ctrl+Alt+O")
        pronunciation_bootstrap_action.triggered.connect(self.open_pronunciation_bootstrap)
        translation_menu.addAction(pronunciation_bootstrap_action)

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
        """Single source-of-truth current project context for workspace-level panels."""
        return self.current_project_id

    def open_translation_management(self, project_id: Optional[int] = None, push_history: bool = True):
        """Open translation management panel."""
        logger.info("Opening translation management panel")

        normalized_pid = self._normalize_optional_project_id(project_id)
        context_project_id = normalized_pid if normalized_pid is not None else self._get_active_project_id()
        key = "workspace.tm"
        existing = self._resolve_workspace_instance(key)
        if isinstance(existing, TranslationManagementPanel):
            existing_pid = getattr(existing, "project_id", None)
            if existing_pid == context_project_id:
                self.stack.setCurrentWidget(existing)
                self._set_active_workspace(key, push_history=push_history)
                self._refresh_workspace_badges()
                self._show_nav_status("Translation Management focused.")
                return
            # Context changed: replace instance deterministically.
            self._remove_widget_from_stack(existing)
            self._unregister_workspace_instance(key)

        def _factory():
            tm_panel = TranslationManagementPanel(project_id=context_project_id)
            tm_panel.back_requested.connect(self._navigate_workspace_back)
            tm_panel.open_user_dictionaries_requested.connect(
                lambda pid=context_project_id: self.open_user_dictionaries(project_id=pid)
            )
            tm_panel.go_to_source_requested.connect(self._on_audio_go_to_source_requested)
            tm_panel.destroyed.connect(lambda *_args: self._unregister_workspace_instance(key))
            return tm_panel

        self._focus_or_create_workspace_widget(key, _factory)
        self._set_active_workspace(key, push_history=push_history)
        self._refresh_workspace_badges()
        self._show_nav_status("Translation Management opened.")

    def open_user_dictionaries(self, project_id: Optional[int] = None, push_history: bool = True):
        """Open User Dictionaries workspace."""
        logger.info("Opening user dictionaries workspace")

        normalized_pid = self._normalize_optional_project_id(project_id)
        context_project_id = normalized_pid if normalized_pid is not None else self._get_active_project_id()
        key = "workspace.user_dictionaries"
        existing = self._resolve_workspace_instance(key)
        if isinstance(existing, UserDictionariesView):
            existing_pid = getattr(existing, "project_id", None)
            if existing_pid == context_project_id:
                self.stack.setCurrentWidget(existing)
                self._set_active_workspace(key, push_history=push_history)
                self._refresh_workspace_badges()
                self._show_nav_status("User Dictionaries focused.")
                return
            self._remove_widget_from_stack(existing)
            self._unregister_workspace_instance(key)

        def _factory():
            panel = UserDictionariesView(project_id=context_project_id, show_back_button=True)
            panel.back_requested.connect(self._navigate_workspace_back)
            panel.open_translation_management_requested.connect(
                lambda pid=context_project_id: self.open_translation_management(project_id=pid)
            )
            panel.destroyed.connect(lambda *_args: self._unregister_workspace_instance(key))
            return panel

        self._focus_or_create_workspace_widget(key, _factory)
        self._set_active_workspace(key, push_history=push_history)
        self._refresh_workspace_badges()
        self._show_nav_status("User Dictionaries opened.")

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

    def open_pronunciation_bootstrap(self):
        """Open pronunciation bootstrap dialog."""
        from app.ui.dialogs.pronunciation_bootstrap_dialog import show_pronunciation_bootstrap_dialog

        logger.info("Opening pronunciation bootstrap dialog")
        show_pronunciation_bootstrap_dialog(parent=self)

    def open_project(self, project_id: int):
        """Open a project view."""
        logger.info(f"Opening project {project_id}")

        try:
            pid = int(project_id)
        except (TypeError, ValueError):
            self._show_nav_status("Invalid project ID.")
            return
        if not self._is_valid_project_id(pid):
            self._show_nav_status(f"Project #{pid} does not exist.")
            return

        project_view = self._project_instances.get(pid)
        if project_view is not None and self._is_widget_in_stack(project_view):
            self.stack.setCurrentWidget(project_view)
            self._set_active_workspace("workspace.projects")
            self._set_current_project_context(pid)
            self._push_recent_project(pid)
            pending_tab = self._pending_project_tab
            self._pending_project_tab = None
            if pending_tab and project_view.focus_tab(pending_tab):
                self._show_nav_status(f"Project #{pid} focused. Routed to {pending_tab.replace('_', ' ').title()}.")
            else:
                self._show_nav_status(f"Project #{pid} focused.")
            return

        # Create project view
        project_key = f"project:{pid}"
        project_view = ProjectView(pid)
        project_view.back_to_dashboard.connect(self.back_to_dashboard)
        project_view.open_translation_management_requested.connect(self.open_translation_management)
        project_view.destroyed.connect(
            lambda *_args, _pid=pid, _key=project_key: (
                self._project_instances.pop(_pid, None),
                self._unregister_workspace_instance(_key),
            )
        )

        # Add to stack and show
        self.stack.addWidget(project_view)
        self.stack.setCurrentWidget(project_view)
        self._project_instances[pid] = project_view
        self._register_workspace_instance(project_key, project_view)
        self._set_active_workspace("workspace.projects")
        self._set_current_project_context(pid)
        self._push_recent_project(pid)
        pending_tab = self._pending_project_tab
        self._pending_project_tab = None
        if pending_tab and project_view.focus_tab(pending_tab):
            self._show_nav_status(f"Project #{pid} opened. Routed to {pending_tab.replace('_', ' ').title()}.")
        else:
            self._show_nav_status(f"Project #{pid} opened.")

    def _find_project_view(self, project_id: int) -> Optional[ProjectView]:
        cached = self._project_instances.get(project_id)
        if cached is not None and self._is_widget_in_stack(cached):
            return cached
        for i in range(self.stack.count()):
            widget = self.stack.widget(i)
            if isinstance(widget, ProjectView) and getattr(widget, "project_id", None) == project_id:
                self._project_instances[project_id] = widget
                return widget
        self._project_instances.pop(project_id, None)
        return None

    def _open_or_focus_project(self, project_id: int) -> Optional[ProjectView]:
        project_view = self._find_project_view(project_id)
        if project_view is None:
            self.open_project(project_id)
            project_view = self.stack.currentWidget()
            if not isinstance(project_view, ProjectView):
                return None
        self.stack.setCurrentWidget(project_view)
        self._set_active_workspace("workspace.projects")
        self._set_current_project_context(project_id)
        self._push_recent_project(project_id)
        return project_view

    def _focus_project_source_row(self, project_view: ProjectView, kind: str, source_id: int) -> bool:
        kind_norm = (kind or "").strip().lower()
        if kind_norm in {"term_cluster", "term"}:
            project_view.tabs.setCurrentWidget(project_view.terms_view)
            return bool(project_view.terms_view.focus_term_by_id(source_id))
        if kind_norm == "lemma":
            project_view.tabs.setCurrentWidget(project_view.dictionary_view)
            return bool(project_view.dictionary_view.focus_lemma_by_id(source_id))
        if kind_norm in {"sentence", "sentences", "surface"}:
            project_view.tabs.setCurrentWidget(project_view.sentences_view)
            return bool(project_view.sentences_view.focus_sentence_by_id(source_id))
        return False

    def _resolve_sentence_source_id(self, project_id: int, source_text: str) -> Optional[int]:
        text = (source_text or "").strip()
        if not text:
            return None
        try:
            from sqlalchemy import select

            from app.infra.sa_models import DocumentSentence, SourceCorpus, SourceDocument
            from app.services.db_service import DBService

            stmt = (
                select(DocumentSentence.sentence_id)
                .join(SourceDocument, DocumentSentence.doc_id == SourceDocument.doc_id)
                .join(SourceCorpus, SourceDocument.corpus_id == SourceCorpus.corpus_id)
                .where(
                    SourceCorpus.project_id == project_id,
                    DocumentSentence.text == text,
                )
                .order_by(DocumentSentence.sentence_id.asc())
                .limit(1)
            )
            with DBService.get_instance().get_session() as session:
                value = session.execute(stmt).scalar()
            return int(value) if value is not None else None
        except Exception as exc:
            logger.debug("Failed to resolve sentence source id: %s", exc)
            return None

    def _on_audio_go_to_source_requested(self, payload: dict) -> None:
        """Best-effort navigation from Audio Player queue to the owning source row."""
        if not isinstance(payload, dict):
            return

        kind = str(payload.get("kind") or "").strip()
        kind_norm = kind.lower()
        source_id = payload.get("source_id")
        project_id = payload.get("project_id")
        source_text = str(payload.get("source_text") or "").strip()
        if not kind or project_id is None:
            self.statusBar().showMessage("Go to Source is unavailable for this queue row", 4000)
            return

        try:
            project_id_int = int(project_id)
        except (TypeError, ValueError):
            self.statusBar().showMessage("Go to Source payload is invalid", 4000)
            return

        source_id_int: Optional[int] = None
        if source_id is not None:
            try:
                source_id_int = int(source_id)
            except (TypeError, ValueError):
                source_id_int = None

        if source_id_int is None and kind_norm in {"sentence", "sentences", "surface"}:
            source_id_int = self._resolve_sentence_source_id(project_id_int, source_text)
            kind = "sentence"

        if source_id_int is None:
            self.statusBar().showMessage("Go to Source is unavailable for this queue row", 4000)
            return

        project_view = self._open_or_focus_project(project_id_int)
        if project_view is None:
            self.statusBar().showMessage("Failed to open project for source navigation", 4000)
            return

        max_attempts = 12
        retry_ms = 200

        def _attempt_focus(attempt: int = 0) -> None:
            focused = self._focus_project_source_row(project_view, kind, source_id_int)
            if focused:
                return
            if attempt + 1 >= max_attempts:
                self.statusBar().showMessage(
                    "Source row was not found on currently loaded page",
                    5000,
                )
                return
            QTimer.singleShot(retry_ms, lambda: _attempt_focus(attempt + 1))

        _attempt_focus()

    def _on_audio_player_data_changed(self, payload: dict) -> None:
        """Collect refresh hints from Audio Player and debounce cross-view reload."""
        if not isinstance(payload, dict):
            return
        fields = payload.get("fields") or []
        project_ids = payload.get("project_ids") or []
        for field in fields:
            value = str(field or "").strip().lower()
            if value:
                self._pending_refresh_fields.add(value)
        parsed_project_ids: Set[int] = set()
        for pid in project_ids:
            try:
                parsed_project_ids.add(int(pid))
            except (TypeError, ValueError):
                continue
        if parsed_project_ids:
            self._pending_refresh_project_ids.update(parsed_project_ids)
        else:
            self._pending_refresh_all_projects = True
        if not self._cross_refresh_timer.isActive():
            self._cross_refresh_timer.start()

    def _flush_cross_view_refresh(self) -> None:
        """Apply one debounced refresh pass to relevant open views."""
        project_filter: Optional[Set[int]]
        if self._pending_refresh_all_projects:
            project_filter = None
        else:
            project_filter = set(self._pending_refresh_project_ids)
        self._pending_refresh_fields.clear()
        self._pending_refresh_project_ids.clear()
        self._pending_refresh_all_projects = False
        self._refresh_open_views(project_filter=project_filter)

    def _refresh_open_views(self, *, project_filter: Optional[Set[int]]) -> None:
        """Refresh open views for affected projects (or all when project_filter is None)."""
        for i in range(self.stack.count()):
            widget = self.stack.widget(i)
            if widget is None:
                continue
            try:
                if isinstance(widget, ProjectView):
                    if project_filter is not None and widget.project_id not in project_filter:
                        continue
                    if hasattr(widget, "dictionary_view") and widget.dictionary_view is not None:
                        widget.dictionary_view.refresh()
                    if hasattr(widget, "terms_view") and widget.terms_view is not None:
                        widget.terms_view.perform_search()
                    if hasattr(widget, "sentences_view") and widget.sentences_view is not None:
                        widget.sentences_view._reload()
                    if hasattr(widget, "term_card_view") and widget.term_card_view is not None:
                        widget.term_card_view.load_review_queue()
                    if hasattr(widget, "user_dictionaries_view") and widget.user_dictionaries_view is not None:
                        widget.user_dictionaries_view.load_items()
                        if getattr(widget.user_dictionaries_view, "_view_mode", "browse") == "review":
                            widget.user_dictionaries_view.load_review_queue(reset_index=False)
                    continue

                if isinstance(widget, TranslationManagementPanel):
                    wid_pid = getattr(widget, "project_id", None)
                    if project_filter is None or wid_pid is None or wid_pid in project_filter:
                        widget.perform_search()
                    continue

                if isinstance(widget, UserDictionariesView):
                    wid_pid = getattr(widget, "project_id", None)
                    if project_filter is None or wid_pid is None or wid_pid in project_filter:
                        widget.load_items()
                        if getattr(widget, "_view_mode", "browse") == "review":
                            widget.load_review_queue(reset_index=False)
                    continue
            except Exception as exc:
                logger.debug("Cross-view refresh skipped for %s: %s", type(widget).__name__, exc)

    def back_to_dashboard(self, push_history: bool = True):
        """Return to Projects dashboard (deterministic home)."""
        logger.info("Returning to dashboard")
        # Keep existing workspace/project instances alive; focus home only.
        self.stack.setCurrentWidget(self.dashboard)
        self._set_active_workspace("workspace.projects", push_history=push_history)
        self.dashboard.load_projects()
        self._show_nav_status("Projects dashboard opened.")

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
            action_id="tools.pronunciation_bootstrap",
            title="Pronunciation Bootstrap",
            keywords=["pronunciation", "phonikud", "niqqud", "bootstrap", "offline"],
            shortcut="Ctrl+Alt+O",
            callback=self.open_pronunciation_bootstrap,
            category="Tools"
        ))

        registry.register(ActionSpec(
            action_id="premium.audio_player",
            title="Toggle Audio Player",
            keywords=["audio", "playback", "now playing", "queue", "dock"],
            shortcut="Ctrl+Alt+L",
            callback=self.open_audio_workspace,
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

    def _save_sidebar_sections_state(self, state: Dict[str, bool]) -> None:
        try:
            self.settings.set_json("workspace/sidebar_sections", state)
        except Exception as exc:
            logger.warning("Failed to save sidebar sections state: %s", exc)

    def _restore_sidebar_sections_state(self) -> None:
        try:
            data = self.settings.get_json("workspace/sidebar_sections", {})
            if not isinstance(data, dict):
                data = {}
            self.workspace.sidebar.set_sections_state(data)
        except Exception as exc:
            logger.warning("Failed to restore sidebar sections state: %s", exc)

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
        if self._on_workspace_sidebar_open_project(action_id):
            return

        action_map = {
            "workspace.projects": self.back_to_dashboard,
            "workspace.tm": self.open_translation_management,
            "workspace.user_dictionaries": self.open_user_dictionaries,
            "workspace.audio": self.open_audio_workspace,
            "workspace.current_project.open": self._open_current_project,
            "workspace.project_tab.documents": lambda: self._open_current_project_tab("documents"),
            "workspace.project_tab.sentences": lambda: self._open_current_project_tab("sentences"),
            "workspace.project_tab.dictionary": lambda: self._open_current_project_tab("dictionary"),
            "workspace.project_tab.terms": lambda: self._open_current_project_tab("terms"),
            "workspace.project_tab.term_cards": lambda: self._open_current_project_tab("term_cards"),
            "workspace.project_tab.export": lambda: self._open_current_project_tab("export"),
            "workspace.refresh_badges": self._refresh_workspace_badges,
            "navigate.dashboard": self.back_to_dashboard,
            "tools.verification": self.open_verification,
            "tools.import_dictionary": self.open_import_wizard,
            "premium.tm": self.open_translation_management,
            "premium.coverage": self.open_coverage,
            "premium.audio_player": self.open_audio_workspace,
        }

        handler = action_map.get(action_id)
        if handler:
            handler()
        else:
            logger.warning(f"Unknown sidebar action: {action_id}")
            self._show_nav_status("Unsupported sidebar action.")

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
        options = ExportOptions(include_snapshots=True, include_pronunciation_metadata=True)
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
