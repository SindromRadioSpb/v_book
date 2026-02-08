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

logger = logging.getLogger(__name__)


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

        self.init_ui()
        self.load_initial_data()

    def init_ui(self):
        """Initialize the UI."""
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

        # Row 2: Status + Scope + Origin
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Status:"))
        self.status_combo = QComboBox()
        self.status_combo.addItems(["All", "draft", "approved", "rejected", "deprecated"])
        self.status_combo.currentTextChanged.connect(self.on_filter_changed)
        row2.addWidget(self.status_combo)

        row2.addWidget(QLabel("Scope:"))
        self.scope_combo = QComboBox()
        if self.project_id:
            self.scope_combo.addItems(["Project", "Global", "All"])
        else:
            self.scope_combo.addItems(["Global", "All"])
        self.scope_combo.currentTextChanged.connect(self.on_filter_changed)
        row2.addWidget(self.scope_combo)

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
        self.table_view.horizontalHeader().setStretchLastSection(True)

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
        self.perform_search()

    def on_clear_filters(self):
        """Clear all filters."""
        self.search_edit.clear()
        self.source_ref_edit.clear()
        self.kind_combo.setCurrentIndex(0)
        self.status_combo.setCurrentIndex(0)
        self.scope_combo.setCurrentIndex(0)
        self.origin_combo.setCurrentIndex(0)
        self.perform_search()

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

        # Scope
        scope = self.scope_combo.currentText().lower()
        if scope != "all":
            filters["scope"] = scope
            if scope == "project" and self.project_id:
                filters["project_id"] = self.project_id

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
        """Perform search with current filters."""
        if self.worker and self.worker.isRunning():
            logger.warning("Search already in progress, skipping")
            return

        self.current_filters = self.build_filters()
        self.status_label.setText("Searching...")
        self.cancel_btn.setEnabled(True)

        # Start worker
        self.worker = TMSearchWorker(
            filters=self.current_filters,
            limit=100,
            offset=0,
        )
        self.worker.results_ready.connect(self.on_search_results)
        self.worker.error.connect(self.on_search_error)
        self.worker.finished.connect(lambda: self.cancel_btn.setEnabled(False))
        self.worker.start()

    def on_search_results(self, entries: List[TMEntryDTO], total_count: int):
        """Handle search results."""
        self.model.update_entries(entries, total_count)
        self.results_label.setText(f"Results: {len(entries)} of {total_count}")
        self.status_label.setText("Ready")
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
        """Handle panel close - stop workers."""
        if self.worker and self.worker.isRunning():
            logger.info("Stopping TM search worker on panel close")
            self.worker.terminate()
            self.worker.wait()
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

    def on_back(self):
        """Handle back button click."""
        self.back_requested.emit()
