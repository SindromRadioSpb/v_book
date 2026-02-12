"""P2 Translation Management Panel - Premium UI for TM administration.

Allows users to:
- Search and filter TM entries
- Edit translations inline
- Approve/reject/deprecate entries
- View history and revert changes
"""

import logging
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
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont

from app.services.db_service import DBService
from app.ui.models_qt import TranslationManagementTableModel
from app.ui.workers import TMSearchWorker
from app.domain.dto import TMEntryDTO
from app.infra.settings import SettingsService

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

    def __init__(self, project_id: Optional[int] = None):
        super().__init__()
        self.project_id = project_id
        self.worker: Optional[TMSearchWorker] = None
        self.model = TranslationManagementTableModel()
        self.current_filters = {}
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(500)  # 500ms debounce
        self.search_timer.timeout.connect(self.perform_search)

        # Settings service for persistence
        self.settings = SettingsService.get_instance()

        # State: selected project IDs (None = all projects)
        self.selected_project_ids: Optional[List[int]] = None
        self.all_projects = []  # Loaded in init_ui

        # State: pagination
        self.current_page = 1
        self.page_size = self.settings.get_int("tm_panel/page_size", 100)
        self.total_count = 0

        # State: sorting
        self.sort_column = self.settings.get_string("tm_panel/sort_column", "updated_at")
        self.sort_direction = self.settings.get_string("tm_panel/sort_direction", "desc")

        # Column index to DB column mapping
        self.COLUMN_TO_DB = {
            0: "tm_id",
            1: "kind",
            2: "src_text",
            3: "translation",
            4: "status",
            5: "project_id",
            6: "origin",
            7: "source_ref",
            8: "updated_at",
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
        header_layout.addStretch()

        back_btn = QPushButton("← Back")
        back_btn.clicked.connect(self.on_back)
        header_layout.addWidget(back_btn)

        layout.addLayout(header_layout)

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

        filters_layout.addLayout(row3)

        filters_group.setLayout(filters_layout)
        layout.addWidget(filters_group)

        # Table
        table_group = QGroupBox("TM Entries")
        table_layout = QVBoxLayout()

        self.table_view = QTableView()
        self.table_view.setModel(self.model)
        self.table_view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSortingEnabled(False)  # Server-side sorting only

        # Enable clickable headers for server-side sorting
        header = self.table_view.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionsClickable(True)
        header.sectionClicked.connect(self.on_header_clicked)

        # Restore header state (column widths)
        self.settings.restore_header_state("tm_panel", header)

        # Install event filter for Enter key editing
        self.table_view.installEventFilter(self)

        # P2 FIX: Connect dataChanged signal to save inline edits
        self.model.dataChanged.connect(self.on_translation_edited)

        # Column widths
        self.table_view.setColumnWidth(0, 60)   # ID
        self.table_view.setColumnWidth(1, 100)  # Kind
        self.table_view.setColumnWidth(2, 150)  # Source
        self.table_view.setColumnWidth(3, 150)  # Translation
        self.table_view.setColumnWidth(4, 100)  # Status
        self.table_view.setColumnWidth(5, 100)  # Scope
        self.table_view.setColumnWidth(6, 100)  # Origin

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

    def on_search_text_changed(self):
        """Handle search text change with debounce."""
        self.search_timer.start()

    def on_filter_changed(self):
        """Handle filter combo change."""
        self.current_page = 1  # Reset to first page when filters change
        self.perform_search()

    def on_clear_filters(self):
        """Clear all filters."""
        self.search_edit.clear()
        self.source_ref_edit.clear()
        self.kind_combo.setCurrentIndex(0)
        self.status_combo.setCurrentIndex(0)
        self.origin_combo.setCurrentIndex(0)
        # Reset projects to "All"
        self.selected_project_ids = None
        self.update_projects_button_label()
        self.perform_search()

    def on_select_projects(self):
        """Open project selection dialog."""
        dialog = ProjectSelectDialog(self.all_projects, self.selected_project_ids, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.selected_project_ids = dialog.get_selected_ids()
            self.update_projects_button_label()
            self.current_page = 1  # Reset to first page when filter changes
            self.perform_search()

    def update_projects_button_label(self):
        """Update projects button label to show selection."""
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

        # Save header state (column widths)
        header = self.table_view.horizontalHeader()
        self.settings.save_header_state("tm_panel", header)

        event.accept()

    def on_translation_edited(self, top_left, bottom_right, roles):
        """P2 FIX: Handle inline edit of translation - save to DB.

        Args:
            top_left: Top-left index of changed cells
            bottom_right: Bottom-right index of changed cells
            roles: Roles that changed
        """
        # Check if Translation column was edited (col 3)
        if top_left.column() != 3:
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
                        # Start editing Translation column (column 3)
                        translation_index = self.model.index(current_index.row(), 3)
                        self.table_view.setCurrentIndex(translation_index)
                        self.table_view.edit(translation_index)
                        return True  # Event handled

        return super().eventFilter(obj, event)

    def on_back(self):
        """Handle back button click."""
        self.back_requested.emit()
