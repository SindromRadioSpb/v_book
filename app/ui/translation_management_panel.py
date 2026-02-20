"""P2 Translation Management Panel - Premium UI for TM administration.

Allows users to:
- Search and filter TM entries
- Edit translations inline
- Approve/reject/deprecate entries
- View history and revert changes
"""

import logging
from datetime import datetime
from typing import Optional, List

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QComboBox,
    QPushButton,
    QTableView,
    QMessageBox,
    QDialog,
    QDialogButtonBox,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QCheckBox,
    QMenu,
    QProgressDialog,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QAction

from app.services.db_service import DBService
from app.services.audio_playback_service import AudioPlaybackService
from app.ui.models_qt import TranslationManagementTableModel
from app.ui.workers import TMSearchWorker, TMExportWorker
from app.ui.table_layout_controller import TableLayoutController
from app.ui.delegates.audio_play_delegate import AudioPlayDelegate
from app.domain.dto import TMEntryDTO
from app.domain.normalization.normalizer import normalize_for_tm
from app.infra.settings import SettingsService
from app.ui.dialogs.add_to_user_dictionary_dialog import show_add_to_user_dictionary_dialog
from app.ui.dialogs.edit_pronunciation_dialog import show_edit_pronunciation_dialog
from app.ui.workers import UserDictionaryBulkAddWorker

logger = logging.getLogger(__name__)


class ProjectSelectDialog(QDialog):
    """Dialog for selecting multiple projects to filter TM entries."""

    def __init__(self, all_projects: List, selected_ids: Optional[List[int]], parent=None):
        """
        Args:
            all_projects: List of DictProject instances
            selected_ids: List of currently selected project IDs (None = all projects)
            parent: Parent widget
        """
        super().__init__(parent)
        self.all_projects = all_projects
        self.selected_ids = selected_ids if selected_ids is not None else []
        self.init_ui()

    def init_ui(self):
        """Initialize UI."""
        self.setWindowTitle("Select Projects")
        self.setMinimumSize(400, 500)

        layout = QVBoxLayout()

        # Info
        info = QLabel("Select projects to include in search:")
        info.setStyleSheet("font-weight: bold;")
        layout.addWidget(info)

        # List widget with checkboxes
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.NoSelection)

        # Add "Global (no project)" entry
        global_item = QListWidgetItem("Global (no project)")
        global_item.setCheckState(
            Qt.CheckState.Checked if (-1 in self.selected_ids or None in self.selected_ids) else Qt.CheckState.Unchecked
        )
        global_item.setData(Qt.ItemDataRole.UserRole, -1)  # Special ID for global
        self.list_widget.addItem(global_item)

        # Add separator
        separator = QListWidgetItem("─" * 40)
        separator.setFlags(Qt.ItemFlag.NoItemFlags)
        self.list_widget.addItem(separator)

        # Add projects
        for project in self.all_projects:
            item = QListWidgetItem(project.name)
            item.setCheckState(
                Qt.CheckState.Checked if project.project_id in self.selected_ids else Qt.CheckState.Unchecked
            )
            item.setData(Qt.ItemDataRole.UserRole, project.project_id)
            self.list_widget.addItem(item)

        layout.addWidget(self.list_widget)

        # Select/Clear buttons
        buttons_layout = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(self.on_select_all)
        buttons_layout.addWidget(select_all_btn)

        clear_all_btn = QPushButton("Clear All")
        clear_all_btn.clicked.connect(self.on_clear_all)
        buttons_layout.addWidget(clear_all_btn)

        buttons_layout.addStretch()
        layout.addLayout(buttons_layout)

        # OK/Cancel buttons
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.setLayout(layout)

    def on_select_all(self):
        """Select all items."""
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.flags() & Qt.ItemFlag.ItemIsEnabled:
                item.setCheckState(Qt.CheckState.Checked)

    def on_clear_all(self):
        """Clear all selections."""
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.flags() & Qt.ItemFlag.ItemIsEnabled:
                item.setCheckState(Qt.CheckState.Unchecked)

    def get_selected_ids(self) -> Optional[List[int]]:
        """Get list of selected project IDs.

        Returns:
            List of project IDs (with -1 for global), or None if all checked
        """
        selected = []
        all_count = 0

        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.flags() & Qt.ItemFlag.ItemIsEnabled:
                all_count += 1
                if item.checkState() == Qt.CheckState.Checked:
                    project_id = item.data(Qt.ItemDataRole.UserRole)
                    selected.append(project_id)

        # If all items checked, return None (means "All")
        if len(selected) == all_count:
            return None

        return selected


class HistoryDialog(QDialog):
    """Dialog for viewing and reverting history."""

    def __init__(self, tm_id: int, history_entries: List, parent=None):
        super().__init__(parent)
        self.tm_id = tm_id
        self.history_entries = history_entries
        self.selected_version: Optional[int] = None
        self.init_ui()

    def init_ui(self):
        """Initialize UI."""
        self.setWindowTitle("Translation History")
        self.setMinimumSize(600, 400)

        layout = QVBoxLayout()

        # Info
        info = QLabel(f"History for TM Entry #{self.tm_id}")
        info.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(info)

        # History list
        self.list_widget = QListWidget()
        for entry in self.history_entries:
            item_text = (
                f"Version {entry.version} - {entry.change_kind} - {entry.changed_at}\n"
                f"Translation: {entry.translation}\n"
                f"Status: {entry.status} | Origin: {entry.origin}"
            )
            if entry.notes:
                item_text += f"\nNotes: {entry.notes}"

            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, entry.version)
            self.list_widget.addItem(item)

        self.list_widget.currentItemChanged.connect(self.on_selection_changed)
        layout.addWidget(self.list_widget)

        # Buttons
        button_box = QDialogButtonBox()
        self.revert_btn = button_box.addButton("Revert to Selected", QDialogButtonBox.ButtonRole.ActionRole)
        self.revert_btn.setEnabled(False)
        self.revert_btn.clicked.connect(self.on_revert)

        close_btn = button_box.addButton(QDialogButtonBox.StandardButton.Close)
        close_btn.clicked.connect(self.reject)

        layout.addWidget(button_box)

        self.setLayout(layout)

    def on_selection_changed(self, current, previous):
        """Handle selection change."""
        if current:
            self.selected_version = current.data(Qt.ItemDataRole.UserRole)
            self.revert_btn.setEnabled(True)
        else:
            self.selected_version = None
            self.revert_btn.setEnabled(False)

    def on_revert(self):
        """Handle revert button click."""
        if self.selected_version is not None:
            # Confirm
            reply = QMessageBox.question(
                self,
                "Confirm Revert",
                f"Revert to version {self.selected_version}?\n\n"
                "This will restore the translation, notes, and status from that version.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )

            if reply == QMessageBox.StandardButton.Yes:
                self.accept()


class TranslationManagementPanel(QWidget):
    """P2 Translation Management Panel."""

    back_requested = pyqtSignal()
    open_user_dictionaries_requested = pyqtSignal()

    def __init__(self, project_id: Optional[int] = None):
        super().__init__()
        self.project_id = project_id
        self.worker: Optional[TMSearchWorker] = None
        self.export_worker: Optional[TMExportWorker] = None
        self.batch_translate_worker = None
        self.batch_audio_worker = None
        self.audio_playback_service = AudioPlaybackService()
        self.bulk_worker: Optional['BulkNoiseUpdateWorker'] = None
        self.bulk_progress_dialog: Optional[QProgressDialog] = None
        self.model = TranslationManagementTableModel()
        self.current_filters = {}
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(500)  # 500ms debounce
        self.search_timer.timeout.connect(self.perform_search)

        # Settings service for persistence
        self.settings = SettingsService.get_instance()
        self._scope_setting_key = (
            "tm_panel/scope_mode_project" if self.project_id is not None else "tm_panel/scope_mode_global"
        )

        # State: selected project IDs (None = all projects)
        self.selected_project_ids: Optional[List[int]] = None
        self.all_projects = []  # Loaded in init_ui
        self.scope_mode = self.settings.get_string(
            self._scope_setting_key,
            "current_project" if self.project_id is not None else "global",
        )
        if self.scope_mode not in ("global", "current_project"):
            self.scope_mode = "global"
        if self.scope_mode == "current_project" and self.project_id is None:
            self.scope_mode = "global"

        # State: pagination
        self.current_page = 1
        self.page_size = self.settings.get_int("tm_panel/page_size", 100)
        self.total_count = 0

        # State: sorting
        self.sort_column = self.settings.get_string("tm_panel/sort_column", "updated_at")
        self.sort_direction = self.settings.get_string("tm_panel/sort_direction", "desc")

        # Column index to DB column mapping
        self.COLUMN_TO_DB = {
            0: "ud_marker",
            1: "tm_id",
            2: "kind",
            3: "src_text",
            4: "translation",
            5: "status",
            6: "project_id",
            7: "origin",
            8: "source_ref",
            9: "updated_at",
            11: "last_review",
            12: "pronunciation",
            13: "audio_status",
        }

        self.init_ui()
        self.load_initial_data()

    def init_ui(self):
        """Initialize the UI."""
        # Load all projects for multi-project filter
        try:
            from app.services.project_service import ProjectService
            db_service = DBService.get_instance()
            project_service = ProjectService()
            with db_service.get_session() as session:
                self.all_projects = project_service.list_projects(session)
        except Exception as e:
            logger.error(f"Failed to load projects: {e}", exc_info=True)
            self.all_projects = []

        layout = QVBoxLayout()

        # Header
        header_layout = QHBoxLayout()
        title = QLabel("Translation Management")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        header_layout.addWidget(title)
        self.open_user_dict_btn = QPushButton("Open User Dictionaries")
        self.open_user_dict_btn.clicked.connect(self.open_user_dictionaries_requested.emit)
        header_layout.addWidget(self.open_user_dict_btn)
        header_layout.addStretch()

        back_btn = QPushButton("Projects Dashboard")
        back_btn.clicked.connect(self.on_back)
        header_layout.addWidget(back_btn)

        layout.addLayout(header_layout)

        scope_layout = QHBoxLayout()
        scope_layout.addWidget(QLabel("Scope:"))

        self.scope_current_btn = QPushButton("Current Project")
        self.scope_current_btn.setCheckable(True)
        self.scope_current_btn.clicked.connect(lambda: self.on_scope_changed("current_project"))
        scope_layout.addWidget(self.scope_current_btn)

        self.scope_global_btn = QPushButton("Global")
        self.scope_global_btn.setCheckable(True)
        self.scope_global_btn.clicked.connect(lambda: self.on_scope_changed("global"))
        scope_layout.addWidget(self.scope_global_btn)

        self.scope_status_label = QLabel("")
        self.scope_status_label.setStyleSheet("color: #666; font-size: 11px;")
        scope_layout.addWidget(self.scope_status_label)

        self.scope_show_all_btn = QPushButton("Show All")
        self.scope_show_all_btn.clicked.connect(lambda: self.on_scope_changed("global"))
        scope_layout.addWidget(self.scope_show_all_btn)
        scope_layout.addStretch()
        layout.addLayout(scope_layout)

        # Filters
        filters_group = QGroupBox("Filters")
        filters_layout = QVBoxLayout()

        # Row 1: Search text + Kind
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Search:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search in source or translation...")
        self.search_edit.textChanged.connect(self.on_search_text_changed)
        row1.addWidget(self.search_edit)

        row1.addWidget(QLabel("Kind:"))
        self.kind_combo = QComboBox()
        self.kind_combo.addItems(["All", "lemma", "term_cluster", "ngram", "surface"])
        self.kind_combo.currentTextChanged.connect(self.on_filter_changed)
        row1.addWidget(self.kind_combo)

        filters_layout.addLayout(row1)

        # Row 2: Status + Projects + Origin
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Status:"))
        self.status_combo = QComboBox()
        self.status_combo.addItems(["All", "draft", "approved", "rejected", "deprecated"])
        self.status_combo.currentTextChanged.connect(self.on_filter_changed)
        row2.addWidget(self.status_combo)

        row2.addWidget(QLabel("Projects:"))
        self.projects_btn = QPushButton("All ▾")
        self.projects_btn.setMinimumWidth(150)
        self.projects_btn.clicked.connect(self.on_select_projects)
        row2.addWidget(self.projects_btn)

        row2.addWidget(QLabel("Origin:"))
        self.origin_combo = QComboBox()
        self.origin_combo.addItems(["All", "user_edit", "import", "mt_accept", "mt_auto", "merge", "revert"])
        self.origin_combo.currentTextChanged.connect(self.on_filter_changed)
        row2.addWidget(self.origin_combo)

        filters_layout.addLayout(row2)

        # Row 3: Source Ref + Clear button
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Source Ref:"))
        self.source_ref_edit = QLineEdit()
        self.source_ref_edit.setPlaceholderText("e.g., dict_import, ui_test...")
        self.source_ref_edit.textChanged.connect(self.on_search_text_changed)
        row3.addWidget(self.source_ref_edit)

        clear_btn = QPushButton("Clear Filters")
        clear_btn.clicked.connect(self.on_clear_filters)
        row3.addWidget(clear_btn)

        # Refresh button to reload data (for sync updates)
        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.setToolTip("Refresh data to see changes from Dictionary/Terms views")
        refresh_btn.clicked.connect(self.on_refresh)
        row3.addWidget(refresh_btn)

        row3.addStretch()

        # Hide Noise checkbox (default: checked)
        self.hide_noise_checkbox = QCheckBox("Hide Noise")
        self.hide_noise_checkbox.setChecked(True)
        self.hide_noise_checkbox.setToolTip("Hide entries marked as noise (punctuation, numbers, etc.)")
        self.hide_noise_checkbox.stateChanged.connect(self.on_filter_changed)
        row3.addWidget(self.hide_noise_checkbox)

        filters_layout.addLayout(row3)

        filters_group.setLayout(filters_layout)
        layout.addWidget(filters_group)

        # Table
        table_group = QGroupBox("TM Entries")
        table_layout = QVBoxLayout()

        self.table_view = QTableView()
        self.table_view.setModel(self.model)
        self.table_view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table_view.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSortingEnabled(False)  # Server-side sorting only

        # Enable clickable headers for server-side sorting
        header = self.table_view.horizontalHeader()
        header.setSectionsClickable(True)
        header.sectionClicked.connect(self.on_header_clicked)

        self.table_layout_controller = TableLayoutController(
            settings=self.settings,
            table_id="tm_panel",
            table=self.table_view,
            default_widths={
                0: 46,   # UD
                1: 70,   # ID
                2: 110,  # Kind
                3: 220,  # Source
                4: 220,  # Translation
                5: 110,  # Status
                6: 110,  # Scope
                7: 110,  # Origin
                8: 170,  # Source Ref
                9: 120,  # Updated
                10: 90,  # Noise
                11: 110, # Last Review
                12: 180, # Niqqud
                13: 90,  # Audio
            },
        )
        self.table_layout_controller.install()
        self.audio_play_delegate = AudioPlayDelegate(
            self.table_view,
            on_play_clicked=self.on_audio_cell_play_clicked,
        )
        self.table_view.setItemDelegateForColumn(13, self.audio_play_delegate)

        # Install event filter for Enter key editing
        self.table_view.installEventFilter(self)

        # P2 FIX: Connect dataChanged signal to save inline edits
        self.model.dataChanged.connect(self.on_translation_edited)
        self.table_view.selectionModel().selectionChanged.connect(self.on_selection_changed)

        # Context menu for noise marking
        self.table_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table_view.customContextMenuRequested.connect(self.on_context_menu)

        table_layout.addWidget(self.table_view)

        # Pagination bar
        pagination_layout = QHBoxLayout()

        # First/Prev buttons
        self.first_btn = QPushButton("«")
        self.first_btn.setToolTip("First page")
        self.first_btn.setMaximumWidth(40)
        self.first_btn.clicked.connect(self.on_first_page)
        pagination_layout.addWidget(self.first_btn)

        self.prev_btn = QPushButton("‹")
        self.prev_btn.setToolTip("Previous page (Ctrl+Left)")
        self.prev_btn.setMaximumWidth(40)
        self.prev_btn.clicked.connect(self.on_prev_page)
        pagination_layout.addWidget(self.prev_btn)

        # Page number input
        pagination_layout.addWidget(QLabel("Page"))
        from PyQt6.QtWidgets import QSpinBox
        self.page_spinbox = QSpinBox()
        self.page_spinbox.setMinimum(1)
        self.page_spinbox.setMaximum(1)
        self.page_spinbox.setValue(1)
        self.page_spinbox.setMaximumWidth(60)
        self.page_spinbox.valueChanged.connect(self.on_page_changed)
        pagination_layout.addWidget(self.page_spinbox)

        self.page_count_label = QLabel("of 1")
        pagination_layout.addWidget(self.page_count_label)

        # Next/Last buttons
        self.next_btn = QPushButton("›")
        self.next_btn.setToolTip("Next page (Ctrl+Right)")
        self.next_btn.setMaximumWidth(40)
        self.next_btn.clicked.connect(self.on_next_page)
        pagination_layout.addWidget(self.next_btn)

        self.last_btn = QPushButton("»")
        self.last_btn.setToolTip("Last page")
        self.last_btn.setMaximumWidth(40)
        self.last_btn.clicked.connect(self.on_last_page)
        pagination_layout.addWidget(self.last_btn)

        pagination_layout.addSpacing(20)

        # Range label
        self.range_label = QLabel("Showing 0–0 of 0")
        pagination_layout.addWidget(self.range_label)

        pagination_layout.addSpacing(20)

        # Page size selector
        pagination_layout.addWidget(QLabel("Page size:"))
        self.page_size_combo = QComboBox()
        self.page_size_combo.addItems(["25", "50", "100", "250", "500"])
        self.page_size_combo.setCurrentText("100")
        self.page_size_combo.currentTextChanged.connect(self.on_page_size_changed)
        pagination_layout.addWidget(self.page_size_combo)

        pagination_layout.addStretch()

        table_layout.addLayout(pagination_layout)

        # Results count
        self.results_label = QLabel("Results: 0")
        self.results_label.setStyleSheet("color: #666; font-size: 11px;")
        table_layout.addWidget(self.results_label)

        table_group.setLayout(table_layout)
        layout.addWidget(table_group)

        # Actions
        actions_layout = QHBoxLayout()

        self.approve_btn = QPushButton("✓ Approve Selected")
        self.approve_btn.setStyleSheet("background: #4caf50; color: white; padding: 6px 12px;")
        self.approve_btn.clicked.connect(lambda: self.on_bulk_action("approved"))
        actions_layout.addWidget(self.approve_btn)

        self.reject_btn = QPushButton("✕ Reject Selected")
        self.reject_btn.setStyleSheet("background: #f44336; color: white; padding: 6px 12px;")
        self.reject_btn.clicked.connect(lambda: self.on_bulk_action("rejected"))
        actions_layout.addWidget(self.reject_btn)

        self.deprecate_btn = QPushButton("⊘ Deprecate Selected")
        self.deprecate_btn.setStyleSheet("background: #ff9800; color: white; padding: 6px 12px;")
        self.deprecate_btn.clicked.connect(lambda: self.on_bulk_action("deprecated"))
        actions_layout.addWidget(self.deprecate_btn)

        self.history_btn = QPushButton("📜 View History")
        self.history_btn.clicked.connect(self.on_view_history)
        actions_layout.addWidget(self.history_btn)

        self.batch_translate_btn = QPushButton("Translate Selected...")
        self.batch_translate_btn.clicked.connect(self.on_batch_translate)
        self.batch_translate_btn.setEnabled(False)
        actions_layout.addWidget(self.batch_translate_btn)

        self.generate_audio_btn = QPushButton("Generate Audio...")
        self.generate_audio_btn.clicked.connect(self.on_generate_audio_selected)
        self.generate_audio_btn.setEnabled(False)
        actions_layout.addWidget(self.generate_audio_btn)

        self.play_audio_btn = QPushButton("Play Audio")
        self.play_audio_btn.clicked.connect(self.on_play_audio_selected)
        self.play_audio_btn.setEnabled(False)
        actions_layout.addWidget(self.play_audio_btn)

        # Task #14: Export Excel button
        self.export_btn = QPushButton("📊 Export Excel")
        self.export_btn.setStyleSheet("background: #2e7d32; color: white; padding: 6px 12px;")
        self.export_btn.clicked.connect(self.on_export_excel)
        actions_layout.addWidget(self.export_btn)

        actions_layout.addStretch()

        self.cancel_btn = QPushButton("✕ Cancel Search")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.on_cancel_search)
        actions_layout.addWidget(self.cancel_btn)

        layout.addLayout(actions_layout)

        # Status bar
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #666; font-size: 11px; padding: 4px;")
        layout.addWidget(self.status_label)

        self.setLayout(layout)
        self._apply_scope_mode(reset_page=False)

    def on_search_text_changed(self):
        """Handle search text change with debounce."""
        self.search_timer.start()

    def on_filter_changed(self):
        """Handle filter combo change."""
        self.current_page = 1  # Reset to first page when filters change
        self.perform_search()

    def _apply_scope_mode(self, reset_page: bool = True):
        """Apply scope selection to project filter state."""
        if self.scope_mode == "current_project" and self.project_id is not None:
            self.selected_project_ids = [self.project_id]
        else:
            self.scope_mode = "global"
            self.selected_project_ids = None

        self.scope_current_btn.blockSignals(True)
        self.scope_global_btn.blockSignals(True)
        self.scope_current_btn.setChecked(self.scope_mode == "current_project")
        self.scope_global_btn.setChecked(self.scope_mode == "global")
        self.scope_current_btn.setEnabled(self.project_id is not None)
        self.scope_current_btn.blockSignals(False)
        self.scope_global_btn.blockSignals(False)

        self.projects_btn.setEnabled(self.scope_mode == "global")
        self.scope_show_all_btn.setVisible(self.scope_mode == "current_project")
        self.settings.set_value(self._scope_setting_key, self.scope_mode)

        if self.scope_mode == "current_project" and self.project_id is not None:
            self.scope_status_label.setText(f"Filtered by: Current Project ({self.project_id})")
        else:
            self.scope_status_label.setText("Filtered by: Global (All projects)")

        self.update_projects_button_label()
        if reset_page:
            self.current_page = 1

    def on_scope_changed(self, scope_mode: str):
        """Handle scope chip click."""
        if scope_mode not in ("global", "current_project"):
            return
        if scope_mode == "current_project" and self.project_id is None:
            QMessageBox.information(
                self,
                "Project Context Required",
                "Current Project scope is available only when opened from a project context.",
            )
            return
        if self.scope_mode == scope_mode:
            return
        self.scope_mode = scope_mode
        self._apply_scope_mode(reset_page=True)
        self.perform_search()

    def on_clear_filters(self):
        """Clear all filters."""
        self.search_edit.clear()
        self.source_ref_edit.clear()
        self.kind_combo.setCurrentIndex(0)
        self.status_combo.setCurrentIndex(0)
        self.origin_combo.setCurrentIndex(0)
        self._apply_scope_mode(reset_page=False)
        self.perform_search()

    def on_refresh(self):
        """Refresh data to reflect changes from Dictionary/Terms views.

        This is needed because bidirectional sync updates the database,
        but the TM Panel UI doesn't auto-refresh when changes occur in other tabs.
        """
        logger.info("User requested manual refresh")
        self.perform_search()

    def on_select_projects(self):
        """Open project selection dialog."""
        if self.scope_mode != "global":
            QMessageBox.information(
                self,
                "Scope Locked",
                "Switch scope to Global to select custom project filters.",
            )
            return
        dialog = ProjectSelectDialog(self.all_projects, self.selected_project_ids, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.selected_project_ids = dialog.get_selected_ids()
            self.update_projects_button_label()
            self.current_page = 1  # Reset to first page when filter changes
            self.perform_search()

    def update_projects_button_label(self):
        """Update projects button label to show selection."""
        if self.scope_mode == "current_project" and self.project_id is not None:
            self.projects_btn.setText(f"Project {self.project_id}")
            return
        if self.selected_project_ids is None:
            self.projects_btn.setText("All ▾")
        else:
            count = len(self.selected_project_ids)
            total = len(self.all_projects) + 1  # +1 for "Global"
            self.projects_btn.setText(f"{count} of {total} ▾")

    @property
    def total_pages(self) -> int:
        """Calculate total pages based on total_count and page_size."""
        if self.total_count == 0:
            return 1
        return (self.total_count + self.page_size - 1) // self.page_size

    @property
    def current_offset(self) -> int:
        """Calculate current offset for pagination."""
        return (self.current_page - 1) * self.page_size

    def on_first_page(self):
        """Navigate to first page."""
        if self.current_page != 1:
            self.current_page = 1
            self.perform_search()

    def on_prev_page(self):
        """Navigate to previous page."""
        if self.current_page > 1:
            self.current_page -= 1
            self.perform_search()

    def on_next_page(self):
        """Navigate to next page."""
        if self.current_page < self.total_pages:
            self.current_page += 1
            self.perform_search()

    def on_last_page(self):
        """Navigate to last page."""
        total = self.total_pages
        if self.current_page != total:
            self.current_page = total
            self.perform_search()

    def on_page_changed(self, page: int):
        """Handle page number change from spinbox."""
        if page != self.current_page:
            self.current_page = page
            self.perform_search()

    def on_page_size_changed(self, size_str: str):
        """Handle page size change."""
        new_size = int(size_str)
        if new_size != self.page_size:
            self.page_size = new_size
            self.settings.set_value("tm_panel/page_size", self.page_size)
            self.current_page = 1  # Reset to first page
            self.perform_search()

    def update_pagination_controls(self):
        """Update pagination control states based on current page and total."""
        total = self.total_pages

        # Update spinbox range
        self.page_spinbox.blockSignals(True)
        self.page_spinbox.setMaximum(total)
        self.page_spinbox.setValue(self.current_page)
        self.page_spinbox.blockSignals(False)

        # Update page count label
        self.page_count_label.setText(f"of {total}")

        # Update button states
        self.first_btn.setEnabled(self.current_page > 1)
        self.prev_btn.setEnabled(self.current_page > 1)
        self.next_btn.setEnabled(self.current_page < total)
        self.last_btn.setEnabled(self.current_page < total)

        # Update range label
        if self.total_count == 0:
            self.range_label.setText("Showing 0–0 of 0")
        else:
            start = self.current_offset + 1
            end = min(self.current_offset + self.page_size, self.total_count)
            self.range_label.setText(f"Showing {start}–{end} of {self.total_count}")

    def on_header_clicked(self, logical_index: int):
        """Handle column header click for server-side sorting.

        Cycle: no sort → ASC → DESC → no sort (default)
        """
        # Get DB column name for this index
        db_column = self.COLUMN_TO_DB.get(logical_index)
        if not db_column:
            return  # Column not sortable

        # Determine new sort state
        if self.sort_column == db_column:
            # Same column: cycle through ASC → DESC → default
            if self.sort_direction == "asc":
                self.sort_direction = "desc"
            else:
                # Reset to default
                self.sort_column = "updated_at"
                self.sort_direction = "desc"
        else:
            # New column: start with ASC
            self.sort_column = db_column
            self.sort_direction = "asc"

        # Update header visuals
        self.update_sort_indicators()

        # Save sort preferences
        self.settings.set_value("tm_panel/sort_column", self.sort_column)
        self.settings.set_value("tm_panel/sort_direction", self.sort_direction)

        # Reset to first page and search
        self.current_page = 1
        self.perform_search()

    def update_sort_indicators(self):
        """Update column header to show sort indicators (▲/▼)."""
        header = self.table_view.horizontalHeader()

        # Find which column index corresponds to current sort_column
        sorted_index = None
        for col_index, db_col in self.COLUMN_TO_DB.items():
            if db_col == self.sort_column:
                sorted_index = col_index
                break

        # Update all column headers
        for col_index in range(self.model.columnCount()):
            col_name = self.model.headerData(col_index, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)

            if col_index == sorted_index:
                # Add sort indicator
                indicator = " ▲" if self.sort_direction == "asc" else " ▼"
                # Remove existing indicators first
                clean_name = col_name.replace(" ▲", "").replace(" ▼", "")
                self.model.setHeaderData(col_index, Qt.Orientation.Horizontal, clean_name + indicator)
            else:
                # Remove indicators from other columns
                clean_name = col_name.replace(" ▲", "").replace(" ▼", "")
                self.model.setHeaderData(col_index, Qt.Orientation.Horizontal, clean_name)

    def build_filters(self) -> dict:
        """Build filters dict from UI."""
        filters = {}

        # Search text
        search_text = self.search_edit.text().strip()
        if search_text:
            filters["search_text"] = search_text

        # Kind
        kind = self.kind_combo.currentText()
        if kind != "All":
            filters["kind"] = kind

        # Status
        status = self.status_combo.currentText()
        if status != "All":
            filters["status"] = status

        # Projects (new multi-project filter)
        if self.selected_project_ids is not None:
            filters["project_ids"] = self.selected_project_ids

        # Origin
        origin = self.origin_combo.currentText()
        if origin != "All":
            filters["origin"] = origin

        # Source Ref
        source_ref = self.source_ref_edit.text().strip()
        if source_ref:
            filters["source_ref"] = source_ref

        # Hide Noise (default: True)
        filters["hide_noise"] = self.hide_noise_checkbox.isChecked()

        return filters

    def perform_search(self):
        """Perform search with current filters and pagination."""
        if self.worker and self.worker.isRunning():
            logger.warning("Search already in progress, skipping")
            return

        self.current_filters = self.build_filters()
        self.status_label.setText("Searching...")
        self.cancel_btn.setEnabled(True)

        # Start worker with pagination and sorting
        self.worker = TMSearchWorker(
            filters=self.current_filters,
            limit=self.page_size,
            offset=self.current_offset,
            sort_column=self.sort_column,
            sort_direction=self.sort_direction,
        )
        self.worker.results_ready.connect(self.on_search_results)
        self.worker.error.connect(self.on_search_error)
        self.worker.finished.connect(lambda: self.cancel_btn.setEnabled(False))
        self.worker.start()

    def on_search_results(self, entries: List[TMEntryDTO], total_count: int):
        """Handle search results."""
        self.total_count = total_count
        self.model.update_entries(entries, total_count)
        self.results_label.setText(f"Results: {len(entries)} of {total_count}")
        self.status_label.setText("Ready")
        self.update_pagination_controls()
        self.on_selection_changed()
        logger.info(f"Search completed: {len(entries)} entries")

    def on_search_error(self, error_msg: str):
        """Handle search error."""
        self.status_label.setText(f"Error: {error_msg}")
        QMessageBox.warning(self, "Search Error", f"Failed to search TM entries:\n{error_msg}")
        logger.error(f"Search error: {error_msg}")

    def load_initial_data(self):
        """Load initial data on panel open."""
        QTimer.singleShot(100, self.perform_search)

    def on_bulk_action(self, new_status: str):
        """Handle bulk status change."""
        selected_indexes = self.table_view.selectionModel().selectedRows()
        if not selected_indexes:
            QMessageBox.information(self, "No Selection", "Please select one or more entries.")
            return

        tm_ids = [self.model.get_entry(idx.row()).tm_id for idx in selected_indexes]

        # Confirm
        reply = QMessageBox.question(
            self,
            "Confirm Bulk Action",
            f"Set status to '{new_status}' for {len(tm_ids)} entries?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Perform action
        try:
            from app.services.translation_admin_service import TranslationAdminService
            service = TranslationAdminService()
            db_service = DBService.get_instance()

            with db_service.get_session() as session:
                count = service.bulk_set_status(session, tm_ids, new_status, approved_by="ui_user")

            QMessageBox.information(self, "Success", f"Updated {count} entries to status '{new_status}'.")
            self.perform_search()  # Refresh

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to update entries:\n{str(e)}")
            logger.error(f"Bulk action error: {e}", exc_info=True)

    def on_view_history(self):
        """View history for selected entry."""
        selected_indexes = self.table_view.selectionModel().selectedRows()
        if not selected_indexes:
            QMessageBox.information(self, "No Selection", "Please select an entry.")
            return

        if len(selected_indexes) > 1:
            QMessageBox.information(self, "Multiple Selection", "Please select only one entry to view history.")
            return

        entry = self.model.get_entry(selected_indexes[0].row())
        tm_id = entry.tm_id

        # Fetch history
        try:
            from app.services.translation_admin_service import TranslationAdminService
            service = TranslationAdminService()
            db_service = DBService.get_instance()

            with db_service.get_session() as session:
                history = service.get_history(session, tm_id)

            if not history:
                QMessageBox.information(self, "No History", f"No history found for TM entry #{tm_id}.")
                return

            # Show dialog
            dialog = HistoryDialog(tm_id, history, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                # Revert
                version = dialog.selected_version
                if version is not None:
                    self.perform_revert(tm_id, version)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to fetch history:\n{str(e)}")
            logger.error(f"History fetch error: {e}", exc_info=True)

    def perform_revert(self, tm_id: int, version: int):
        """Perform revert operation."""
        try:
            from app.services.translation_admin_service import TranslationAdminService
            service = TranslationAdminService()
            db_service = DBService.get_instance()

            with db_service.get_session() as session:
                service.revert(session, tm_id, version, approved_by="ui_user")

            QMessageBox.information(self, "Success", f"Reverted TM entry #{tm_id} to version {version}.")
            self.perform_search()  # Refresh

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to revert:\n{str(e)}")
            logger.error(f"Revert error: {e}", exc_info=True)

    def on_cancel_search(self):
        """Cancel ongoing search."""
        if self.worker and self.worker.isRunning():
            logger.info("Canceling search worker")
            self.worker.terminate()
            self.worker.wait()
            self.worker = None
            self.status_label.setText("Search canceled")
            self.cancel_btn.setEnabled(False)

    def closeEvent(self, event):
        """Handle panel close - stop workers and save preferences."""
        if self.worker and self.worker.isRunning():
            logger.info("Stopping TM search worker on panel close")
            self.worker.terminate()
            self.worker.wait()

        if self.export_worker and self.export_worker.isRunning():
            logger.info("Stopping TM export worker on panel close")
            self.export_worker.cancel()
            self.export_worker.wait()

        if self.batch_translate_worker and self.batch_translate_worker.isRunning():
            logger.info("Stopping TM batch translate worker on panel close")
            self.batch_translate_worker.cancel()
            self.batch_translate_worker.wait()

        if self.batch_audio_worker and self.batch_audio_worker.isRunning():
            logger.info("Stopping TM batch audio worker on panel close")
            self.batch_audio_worker.cancel()
            self.batch_audio_worker.wait()

        if self.bulk_worker and self.bulk_worker.isRunning():
            logger.info("Stopping bulk noise update worker on panel close")
            self.bulk_worker.cancel()
            self.bulk_worker.wait()

        # Save header state (column widths)
        self.table_layout_controller.save_now()

        event.accept()

    def on_translation_edited(self, top_left, bottom_right, roles):
        """P2 FIX: Handle inline edit of translation - save to DB.

        Args:
            top_left: Top-left index of changed cells
            bottom_right: Bottom-right index of changed cells
            roles: Roles that changed
        """
        # Check if Translation column was edited (col 4)
        if top_left.column() != 4:
            return

        row = top_left.row()
        entry = self.model.get_entry(row)

        if not entry:
            return

        new_translation = entry.translation

        # Allow empty translations (user can delete translation)
        try:
            from app.services.translation_admin_service import TranslationAdminService
            service = TranslationAdminService()
            db_service = DBService.get_instance()

            with db_service.get_session() as session:
                # Save translation using service (creates history automatically)
                # Strip whitespace but allow empty string (deletion)
                translation_value = new_translation.strip() if new_translation else ""
                service.update_translation(
                    session,
                    tm_id=entry.tm_id,
                    translation=translation_value,
                )

            logger.info(f"Saved translation for TM entry {entry.tm_id}: {translation_value}")

        except Exception as e:
            logger.error(f"Failed to save translation for TM entry {entry.tm_id}: {e}", exc_info=True)
            QMessageBox.warning(
                self,
                "Save Error",
                f"Failed to save translation:\n{str(e)}"
            )

    def eventFilter(self, obj, event):
        """Handle keyboard shortcuts: Enter (edit), Ctrl+Left/Right (pagination)."""
        if obj == self.table_view and event.type() == event.Type.KeyPress:
            from PyQt6.QtGui import QKeyEvent
            if isinstance(event, QKeyEvent):
                key = event.key()
                modifiers = event.modifiers()

                # Ctrl+Left: Previous page
                if key == Qt.Key.Key_Left and modifiers == Qt.KeyboardModifier.ControlModifier:
                    self.on_prev_page()
                    return True

                # Ctrl+Right: Next page
                if key == Qt.Key.Key_Right and modifiers == Qt.KeyboardModifier.ControlModifier:
                    self.on_next_page()
                    return True

                # Enter: Start editing Translation column
                if key == Qt.Key.Key_Return:
                    current_index = self.table_view.currentIndex()
                    if current_index.isValid():
                        # Start editing Translation column (column 4)
                        translation_index = self.model.index(current_index.row(), 4)
                        self.table_view.setCurrentIndex(translation_index)
                        self.table_view.edit(translation_index)
                        return True  # Event handled

        return super().eventFilter(obj, event)

    def on_export_excel(self):
        """Task #14: Export filtered TM entries to Excel."""
        from PyQt6.QtWidgets import QFileDialog, QProgressDialog

        # Get save file path from user
        default_filename = f"translation_memory_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Translation Memory to Excel",
            default_filename,
            "Excel Files (*.xlsx);;All Files (*)"
        )

        if not file_path:
            return  # User cancelled

        # Ensure .xlsx extension
        if not file_path.endswith('.xlsx'):
            file_path += '.xlsx'

        # Build filters (same as current search)
        filters = self.build_filters()

        # Create progress dialog
        self.export_progress_dialog = QProgressDialog(
            "Preparing export...",
            "Cancel",
            0,
            0,  # Indeterminate progress
            self
        )
        self.export_progress_dialog.setWindowTitle("Exporting to Excel")
        self.export_progress_dialog.setModal(True)
        self.export_progress_dialog.setMinimumDuration(0)
        self.export_progress_dialog.show()

        # Start export worker
        self.export_worker = TMExportWorker(
            file_path=file_path,
            filters=filters,
            sort_column=self.sort_column,
            sort_direction=self.sort_direction,
        )

        # Connect signals
        self.export_worker.progress.connect(self.on_export_progress)
        self.export_worker.export_complete.connect(self.on_export_complete)
        self.export_worker.error.connect(self.on_export_error)
        self.export_progress_dialog.canceled.connect(self.on_export_cancel)

        # Start worker
        self.export_worker.start()

    def on_export_progress(self, message: str):
        """Update export progress dialog."""
        if hasattr(self, 'export_progress_dialog') and self.export_progress_dialog:
            self.export_progress_dialog.setLabelText(message)

    def on_export_complete(self, count: int, file_path: str):
        """Handle export completion."""
        # Close progress dialog
        if hasattr(self, 'export_progress_dialog') and self.export_progress_dialog:
            self.export_progress_dialog.close()
            self.export_progress_dialog = None

        # Show success message
        QMessageBox.information(
            self,
            "Export Complete",
            f"Successfully exported {count:,} entries to:\n{file_path}"
        )

        logger.info(f"TM export completed: {count} entries to {file_path}")

    def on_export_error(self, error_msg: str):
        """Handle export error."""
        # Close progress dialog
        if hasattr(self, 'export_progress_dialog') and self.export_progress_dialog:
            self.export_progress_dialog.close()
            self.export_progress_dialog = None

        # Show error message
        QMessageBox.critical(
            self,
            "Export Failed",
            f"Failed to export TM entries:\n{error_msg}"
        )

        logger.error(f"TM export failed: {error_msg}")

    def on_export_cancel(self):
        """Handle export cancellation."""
        if self.export_worker and self.export_worker.isRunning():
            self.export_worker.cancel()
            logger.info("User cancelled TM export")

    def on_selection_changed(self):
        """Enable/disable translate action based on row selection."""
        if not hasattr(self, "batch_translate_btn"):
            return
        selected_rows = self.table_view.selectionModel().selectedRows()
        has_selection = len(selected_rows) > 0
        self.batch_translate_btn.setEnabled(has_selection)
        self.generate_audio_btn.setEnabled(has_selection)
        self.play_audio_btn.setEnabled(has_selection)

    def _get_selected_tm_entries(self) -> List[TMEntryDTO]:
        """Return selected TM entries in deterministic order."""
        selected_indexes = self.table_view.selectionModel().selectedRows()
        entries: List[TMEntryDTO] = []
        for index in sorted(selected_indexes, key=lambda idx: idx.row()):
            entry = self.model.get_entry(index.row())
            if entry:
                entries.append(entry)
        return entries

    def _get_selected_audio_items(self) -> list[dict]:
        """Build source-audio payloads from selected TM rows."""
        items: list[dict] = []
        for entry in self._get_selected_tm_entries():
            src_norm = (entry.src_norm or "").strip() or normalize_for_tm(
                entry.src_lang, entry.src_text, entry.kind
            ).norm
            if not src_norm:
                continue
            items.append(
                {
                    "row_id": str(entry.tm_id),
                    "src_text": entry.src_text,
                    "src_lang": entry.src_lang,
                    "src_norm": src_norm,
                }
            )
        return items

    def on_batch_translate(self):
        """Handle batch translation for selected TM entries."""
        from app.ui.dialogs import show_batch_translate_dialog
        from app.ui.dialogs.batch_progress_dialog_v3 import BatchProgressDialogV3
        from app.ui.workers import BatchTranslateWorker, TranslateAllFilteredWorker
        from app.services.batch_mt_translate_service import BatchTranslateItem, BatchTranslateOptions
        from app.services.translation_admin_service import TranslationAdminService

        selected_entries = self._get_selected_tm_entries()
        if not selected_entries:
            return

        filtered_count = 0
        admin_service = TranslationAdminService()
        try:
            db_service = DBService.get_instance()
            with db_service.get_session() as session:
                filtered_count = admin_service.count_tm_ids_for_translation(
                    session,
                    self.build_filters(),
                    "FILL_EMPTY",
                )
        except Exception as e:
            logger.warning(f"Failed to compute filtered_count for TM batch translate: {e}")

        accepted, provider_mode, write_mode, scope = show_batch_translate_dialog(
            parent=self,
            selected_count=len(selected_entries),
            scope_enabled=True,
            filtered_count=filtered_count,
        )
        if not accepted:
            return

        if scope == "all_filtered":
            if write_mode == "OVERWRITE" and filtered_count > 100:
                reply = QMessageBox.question(
                    self,
                    "Confirm Overwrite",
                    f"This will overwrite {filtered_count} existing translations.\n\n"
                    f"This action cannot be undone.\n\n"
                    f"Do you want to continue?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return

            # Match User Dictionaries behavior: recalculate total with chosen write_mode.
            total_for_scope = filtered_count
            try:
                db_service = DBService.get_instance()
                with db_service.get_session() as session:
                    total_for_scope = admin_service.count_tm_ids_for_translation(
                        session,
                        self.build_filters(),
                        write_mode,
                    )
            except Exception as e:
                logger.warning(f"Failed to recompute total_for_scope for TM batch translate: {e}")

            logger.info(f"Starting TranslateAllFilteredWorker for {total_for_scope} tm_entry records")
            progress_dialog = BatchProgressDialogV3(parent=self, total=total_for_scope)
            progress_dialog.show()

            worker = TranslateAllFilteredWorker(
                entity_type="tm_entry",
                project_id=self.project_id,
                filters=self.build_filters(),
                provider_mode=provider_mode,
                write_mode=write_mode,
                id_fetch_chunk=200,
                translation_chunk=1,
            )

            worker.progress.connect(progress_dialog.update_progress)
            worker.stats_updated.connect(progress_dialog.update_counts)
            worker.row_translated.connect(progress_dialog.add_recent_item)
            worker.stage_updated.connect(progress_dialog.set_stage)
            worker.finished.connect(lambda result: self.on_batch_translate_finished(result, progress_dialog))
            worker.error.connect(lambda error: self.on_batch_translate_error(error, progress_dialog))
            progress_dialog.cancel_requested.connect(worker.cancel)
            progress_dialog.pause_requested.connect(worker.pause)
            progress_dialog.resume_requested.connect(worker.resume)

            self.batch_translate_btn.setEnabled(False)
            worker.finished.connect(self.on_selection_changed)
            worker.error.connect(self.on_selection_changed)

            worker.start()
            self.batch_translate_worker = worker
            return

        items = [
            BatchTranslateItem(
                entity_type="tm_entry",
                entity_id=str(entry.tm_id),
                source_text=entry.src_text,
                src_lang=entry.src_lang,
                tgt_lang=entry.tgt_lang,
                current_translation=entry.translation,
                project_id=entry.project_id,
            )
            for entry in selected_entries
        ]

        options = BatchTranslateOptions(
            provider_mode=provider_mode,
            write_mode=write_mode,
            chunk_size=1,
            stop_on_error=False,
        )

        progress_dialog = BatchProgressDialogV3(parent=self, total=len(items))
        progress_dialog.show()

        worker = BatchTranslateWorker(
            items=items,
            options=options,
            tab_type="tm",
        )
        worker.progress.connect(progress_dialog.update_progress)
        worker.stats_updated.connect(progress_dialog.update_counts)
        worker.row_translated.connect(progress_dialog.add_recent_item)
        worker.stage_updated.connect(progress_dialog.set_stage)
        worker.finished.connect(lambda result: self.on_batch_translate_finished(result, progress_dialog))
        worker.error.connect(lambda error: self.on_batch_translate_error(error, progress_dialog))
        progress_dialog.cancel_requested.connect(worker.cancel)
        progress_dialog.pause_requested.connect(worker.pause)
        progress_dialog.resume_requested.connect(worker.resume)

        self.batch_translate_btn.setEnabled(False)
        worker.finished.connect(self.on_selection_changed)
        worker.error.connect(self.on_selection_changed)

        worker.start()
        self.batch_translate_worker = worker

    def on_batch_translate_finished(self, result, progress_dialog):
        """Handle TM batch translate completion."""
        progress_dialog.set_completed()
        progress_dialog.update_counts(result.succeeded, result.skipped, result.failed)
        progress_dialog.accept()

        msg = (
            "Translation completed!\n\n"
            f"Total: {result.total}\n"
            f"Succeeded: {result.succeeded}\n"
            f"Skipped: {result.skipped}\n"
            f"Failed: {result.failed}"
        )
        if result.failed > 0:
            QMessageBox.warning(self, "Translation Complete (with errors)", msg)
        else:
            QMessageBox.information(self, "Translation Complete", msg)

        self.perform_search()

        if self.batch_translate_worker:
            self.batch_translate_worker.deleteLater()
            self.batch_translate_worker = None

    def on_batch_translate_error(self, error_msg: str, progress_dialog):
        """Handle TM batch translate error."""
        progress_dialog.reject()
        QMessageBox.critical(self, "Translation Error", error_msg)

        if self.batch_translate_worker:
            self.batch_translate_worker.deleteLater()
            self.batch_translate_worker = None

    def on_generate_audio_selected(self):
        """Generate source-audio for selected TM rows."""
        from app.ui.dialogs.batch_audio_dialog import show_batch_audio_dialog
        from app.ui.dialogs.batch_progress_dialog_v3 import BatchProgressDialogV3
        from app.ui.workers import BatchGenerateAudioWorker

        items = self._get_selected_audio_items()
        if not items:
            return

        accepted, provider_mode, write_mode, _scope = show_batch_audio_dialog(
            parent=self,
            selected_count=len(items),
            scope_enabled=False,
            filtered_count=len(items),
        )
        if not accepted:
            return

        progress_dialog = BatchProgressDialogV3(parent=self, total=len(items))
        progress_dialog.setWindowTitle("Batch Generate Source Audio")
        progress_dialog.show()

        worker = BatchGenerateAudioWorker(
            items=items,
            provider_mode=provider_mode,
            write_mode=write_mode,
            audio_chunk=25,
        )
        self.batch_audio_worker = worker
        worker.progress.connect(progress_dialog.update_progress)
        worker.stats_updated.connect(progress_dialog.update_counts)
        worker.row_translated.connect(progress_dialog.add_recent_item)
        worker.stage_updated.connect(progress_dialog.set_stage)
        worker.finished.connect(lambda result: self._on_generate_audio_finished(result, progress_dialog))
        worker.error.connect(lambda err: self._on_generate_audio_error(err, progress_dialog))
        progress_dialog.cancel_requested.connect(worker.cancel)
        progress_dialog.pause_requested.connect(worker.pause)
        progress_dialog.resume_requested.connect(worker.resume)

        self.generate_audio_btn.setEnabled(False)
        worker.finished.connect(self.on_selection_changed)
        worker.error.connect(self.on_selection_changed)
        worker.start()

    def _on_generate_audio_finished(self, result: dict, progress_dialog):
        progress_dialog.set_completed()
        progress_dialog.update_counts(
            int(result.get("succeeded", 0)),
            int(result.get("skipped", 0)),
            int(result.get("failed", 0)),
        )
        progress_dialog.accept()

        msg = (
            "Audio generation completed.\n\n"
            f"Total: {int(result.get('total', 0))}\n"
            f"Ready: {int(result.get('succeeded', 0))}\n"
            f"Skipped: {int(result.get('skipped', 0))}\n"
            f"Failed: {int(result.get('failed', 0))}"
        )
        if int(result.get("failed", 0)) > 0:
            QMessageBox.warning(self, "Audio Generation Complete (with errors)", msg)
        else:
            QMessageBox.information(self, "Audio Generation Complete", msg)

        if self.batch_audio_worker:
            self.batch_audio_worker.deleteLater()
            self.batch_audio_worker = None
        self.perform_search()

    def _on_generate_audio_error(self, error_msg: str, progress_dialog):
        progress_dialog.reject()
        QMessageBox.warning(self, "Audio Generation Failed", error_msg)
        if self.batch_audio_worker:
            self.batch_audio_worker.deleteLater()
            self.batch_audio_worker = None
        self.on_selection_changed()

    def on_play_audio_selected(self):
        """Play ready audio from selected TM rows using queue mode."""
        items = self._get_selected_audio_items()
        if not items:
            return
        self._play_audio_items(items, play_mode="enqueue")

    def on_audio_cell_play_clicked(self, index):
        """Delegate callback: play one row from Audio column."""
        entry = self.model.get_entry(index.row())
        if not entry:
            return
        src_norm = (entry.src_norm or "").strip() or normalize_for_tm(
            entry.src_lang, entry.src_text, entry.kind
        ).norm
        if not src_norm:
            return
        self._play_audio_items(
            [
                {
                    "src_lang": entry.src_lang,
                    "src_norm": src_norm,
                    "src_text": entry.src_text,
                }
            ],
            play_mode="interrupt",
        )

    def _play_audio_items(self, items: list[dict], *, play_mode: str):
        try:
            with DBService.get_instance().get_session() as session:
                ready_items = self.audio_playback_service.resolve_ready_paths(session, items=items)

            if not ready_items:
                QMessageBox.information(
                    self,
                    "Audio Missing",
                    "No ready audio found for selected rows.\nUse 'Generate Audio...' first.",
                )
                return

            paths = [row[0] for row in ready_items]
            labels = [str((row[1] or {}).get("src_text") or row[0].stem) for row in ready_items]
            self.audio_playback_service.launch_audio_files(paths, labels=labels, play_mode=play_mode)
        except Exception as e:
            logger.error("Failed to play audio in TM Panel: %s", e, exc_info=True)
            QMessageBox.warning(self, "Playback Error", f"Failed to play audio:\n{e}")

    def on_edit_pronunciation_selected(self):
        """Open pronunciation editor for the first selected TM row."""
        items = self._get_selected_audio_items()
        if not items:
            return
        first = items[0]
        changed = show_edit_pronunciation_dialog(
            parent=self,
            src_lang=str(first.get("src_lang") or ""),
            src_norm=str(first.get("src_norm") or ""),
            src_text=str(first.get("src_text") or ""),
        )
        if changed:
            self.perform_search()

    # ========================================================================
    # Noise Marking (Hide Noise + Bulk Mark as Valid/Noise)
    # ========================================================================

    def on_context_menu(self, pos):
        """Show context menu for noise marking."""
        # Get selected rows
        selected_indexes = self.table_view.selectionModel().selectedRows()
        if not selected_indexes:
            return

        count = len(selected_indexes)

        # Create menu
        menu = QMenu(self)

        # Translate selected action (parity with Dictionary/Terms context menu)
        translate_action = QAction(f"Translate Selected ({count:,} rows)...", self)
        translate_action.triggered.connect(self.on_batch_translate)
        menu.addAction(translate_action)

        generate_audio_action = QAction(f"Generate Audio Selected ({count:,} rows)...", self)
        generate_audio_action.triggered.connect(self.on_generate_audio_selected)
        menu.addAction(generate_audio_action)

        play_audio_action = QAction(f"Play Audio Selected ({count:,} rows)", self)
        play_audio_action.triggered.connect(self.on_play_audio_selected)
        menu.addAction(play_audio_action)

        add_to_dict_action = QAction(f"Add Selected to User Dictionary ({count:,} rows)...", self)
        add_to_dict_action.triggered.connect(self.on_add_selected_to_user_dictionary)
        menu.addAction(add_to_dict_action)

        edit_pron_action = QAction("Mispronounced -> Add Pronunciation...", self)
        edit_pron_action.triggered.connect(self.on_edit_pronunciation_selected)
        menu.addAction(edit_pron_action)
        menu.addSeparator()

        # Mark as Noise action
        mark_noise_action = QAction(f"Mark Selected as Noise ({count:,} rows)", self)
        mark_noise_action.triggered.connect(lambda: self.set_entries_noise_status_bulk(True))
        menu.addAction(mark_noise_action)

        # Mark as Valid action
        mark_valid_action = QAction(f"Mark Selected as Valid ({count:,} rows)", self)
        mark_valid_action.triggered.connect(lambda: self.set_entries_noise_status_bulk(False))
        menu.addAction(mark_valid_action)

        # Show menu
        menu.exec(self.table_view.viewport().mapToGlobal(pos))

    def on_add_selected_to_user_dictionary(self):
        """Add selected TM rows to a user dictionary."""
        selected_entries = self._get_selected_tm_entries()
        if not selected_entries:
            return

        payloads = []
        for entry in selected_entries:
            src_norm = normalize_for_tm(entry.src_lang, entry.src_text, entry.kind).norm
            payloads.append(
                {
                    "kind": entry.kind,
                    "src_lang": entry.src_lang,
                    "tgt_lang": entry.tgt_lang,
                    "src_text": entry.src_text,
                    "src_norm": src_norm,
                    "is_noise": 1 if entry.is_noise == 1 else 0,
                    "noise_reason": entry.noise_reason,
                    "origin_project_id": entry.project_id,
                    "origin_entity_type": "tm_entry",
                    "origin_entity_id": entry.tm_id,
                    "origin_tm_entry_id": entry.tm_id,
                    "origin_source_ref": "translation_management_panel",
                }
            )

        accepted, dictionary_id, options = show_add_to_user_dictionary_dialog(
            parent=self,
            selected_count=len(payloads),
        )
        if not accepted or not dictionary_id:
            return

        tags = options.get("tags", [])
        preserve_origin = bool(options.get("preserve_origin_refs", True))
        prepared = []
        for item in payloads:
            row = dict(item)
            if tags:
                row["tags_json"] = tags
            if not preserve_origin:
                row["origin_project_id"] = None
                row["origin_entity_type"] = None
                row["origin_entity_id"] = None
                row["origin_tm_entry_id"] = None
                row["origin_doc_id"] = None
                row["origin_source_ref"] = None
            prepared.append(row)

        progress = QProgressDialog("Adding items to dictionary...", "Cancel", 0, len(prepared), self)
        progress.setWindowTitle("User Dictionaries")
        progress.setModal(True)
        progress.setMinimumDuration(0)
        progress.show()

        worker = UserDictionaryBulkAddWorker(
            dictionary_id=dictionary_id,
            items=prepared,
            include_noise=bool(options.get("include_noise", False)),
            skip_duplicates=bool(options.get("skip_duplicates", True)),
            chunk_size=500,
        )
        self._user_dict_add_worker = worker
        worker.progress.connect(lambda done, total: progress.setValue(done))
        worker.finished.connect(lambda result: self._on_user_dict_add_finished(result, progress))
        worker.error.connect(lambda err: self._on_user_dict_add_error(err, progress))
        progress.canceled.connect(worker.cancel)
        worker.start()

    def _on_user_dict_add_finished(self, result, progress_dialog):
        progress_dialog.close()
        QMessageBox.information(
            self,
            "Add Complete",
            f"Added: {result.get('added', 0)}\n"
            f"Skipped: {result.get('skipped', 0)}\n"
            f"Failed: {result.get('failed', 0)}",
        )
        self._user_dict_add_worker = None

    def _on_user_dict_add_error(self, error_msg: str, progress_dialog):
        progress_dialog.close()
        QMessageBox.warning(self, "Add Failed", error_msg)
        self._user_dict_add_worker = None

    def set_entries_noise_status_bulk(self, is_noise: bool):
        """P0 Safety: Confirmation + progress for bulk noise marking.

        Args:
            is_noise: True = mark as noise, False = mark as valid
        """
        # Get selected rows
        selected_indexes = self.table_view.selectionModel().selectedRows(1)  # Column 1 = tm_id
        if not selected_indexes:
            return

        count = len(selected_indexes)
        status_text = "noise" if is_noise else "valid"

        # Get tm_ids from selection
        tm_ids = []
        source_rows = []
        for index in selected_indexes:
            source_row = index.row()
            source_rows.append(source_row)

            # Get tm_id from model
            tm_id_index = self.model.index(source_row, 1)
            tm_id = self.model.data(tm_id_index, Qt.ItemDataRole.DisplayRole)
            if tm_id:
                tm_ids.append(int(tm_id))

        if not tm_ids:
            return

        # P0: Confirmation dialog for > 100 rows
        if count > 100:
            reply = QMessageBox.question(
                self,
                'Confirm Bulk Action',
                f'You are about to mark {count:,} TM entries as {status_text}.\n\n'
                f'This operation cannot be undone easily.\n\nContinue?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No  # Default to No for safety
            )
            if reply == QMessageBox.StandardButton.No:
                return

        # P0: Use background worker for > 1000 rows
        if count > 1000:
            self._run_bulk_update_worker(tm_ids, source_rows, is_noise)
        else:
            # Fast path: direct update for <= 1000 rows
            self._run_bulk_update_direct(tm_ids, source_rows, is_noise)

    def _run_bulk_update_direct(self, tm_ids: list, source_rows: list, is_noise: bool):
        """Direct bulk update for small datasets (<= 1000 rows)."""
        status_text = "noise" if is_noise else "valid"

        try:
            # Update via service
            from app.services.translation_admin_service import TranslationAdminService
            db_service = DBService.get_instance()
            admin_service = TranslationAdminService()

            with db_service.get_session() as session:
                count = admin_service.set_noise_status_bulk(session, tm_ids, is_noise)

            # Update local model cache
            for row in source_rows:
                # Update is_noise in model (column might not be visible, but update anyway)
                # This is for future UI refresh if we show is_noise column
                pass

            # Show success message
            QMessageBox.information(
                self,
                "Success",
                f"Marked {count:,} TM entries as {status_text}."
            )

            logger.info(f"Marked {count} TM entries as {status_text} (direct update)")

            # Reload data if hide_noise is checked (entries will disappear)
            if is_noise and self.hide_noise_checkbox.isChecked():
                self.perform_search()

        except Exception as e:
            logger.error(f"Failed to bulk update noise status: {e}", exc_info=True)
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to update noise status:\n{str(e)}"
            )

    def _run_bulk_update_worker(self, tm_ids: list, source_rows: list, is_noise: bool):
        """Background worker for large datasets (> 1000 rows) with progress dialog."""
        status_text = "noise" if is_noise else "valid"

        # Create progress dialog
        self.bulk_progress_dialog = QProgressDialog(
            f"Marking {len(tm_ids):,} TM entries as {status_text}...",
            "Cancel",
            0, len(tm_ids),
            self
        )
        self.bulk_progress_dialog.setWindowTitle("Bulk Noise Update")
        self.bulk_progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.bulk_progress_dialog.setMinimumDuration(0)  # Show immediately
        self.bulk_progress_dialog.setValue(0)

        # Create worker
        from app.ui.workers import BulkNoiseUpdateWorker
        self.bulk_worker = BulkNoiseUpdateWorker(
            model_class="TMEntry",  # Use TMEntry instead of Lemma/TermCluster
            item_ids=tm_ids,
            is_noise=is_noise
        )

        # Save context for completion handler
        self.bulk_worker_source_rows = source_rows
        self.bulk_worker_is_noise = is_noise

        # Connect signals
        self.bulk_worker.progress.connect(self._on_bulk_progress)
        self.bulk_worker.update_complete.connect(self._on_bulk_complete)
        self.bulk_worker.error.connect(self._on_bulk_error)
        self.bulk_progress_dialog.canceled.connect(self._on_bulk_cancel)

        # Start worker
        self.bulk_worker.start()

        logger.info(f"Started background worker to mark {len(tm_ids)} TM entries as {status_text}")

    def _on_bulk_progress(self, current: int, total: int):
        """Update bulk progress dialog."""
        if self.bulk_progress_dialog:
            self.bulk_progress_dialog.setValue(current)
            self.bulk_progress_dialog.setLabelText(f"Updated {current:,} of {total:,} TM entries...")

    def _on_bulk_complete(self, count: int):
        """Handle bulk update completion."""
        # Close progress dialog
        if self.bulk_progress_dialog:
            self.bulk_progress_dialog.close()
            self.bulk_progress_dialog = None

        status_text = "noise" if self.bulk_worker_is_noise else "valid"

        # Show success message
        QMessageBox.information(
            self,
            "Success",
            f"Marked {count:,} TM entries as {status_text}."
        )

        logger.info(f"Bulk noise update completed: {count} TM entries marked as {status_text}")

        # Reload data if hide_noise is checked and marking as noise
        if self.bulk_worker_is_noise and self.hide_noise_checkbox.isChecked():
            self.perform_search()

        # Cleanup
        self.bulk_worker = None

    def _on_bulk_error(self, error_msg: str):
        """Handle bulk update error."""
        # Close progress dialog
        if self.bulk_progress_dialog:
            self.bulk_progress_dialog.close()
            self.bulk_progress_dialog = None

        # Show error message
        QMessageBox.critical(
            self,
            "Bulk Update Failed",
            f"Failed to update noise status:\n{error_msg}"
        )

        logger.error(f"Bulk noise update failed: {error_msg}")

        # Cleanup
        self.bulk_worker = None

    def _on_bulk_cancel(self):
        """Handle bulk update cancellation."""
        if self.bulk_worker and self.bulk_worker.isRunning():
            self.bulk_worker.cancel()
            logger.info("User cancelled bulk noise update")

    def on_back(self):
        """Handle back button click."""
        self.back_requested.emit()
