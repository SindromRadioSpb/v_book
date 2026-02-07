"""Project dashboard - main landing page."""
import logging
from typing import List

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTableView,
    QLabel,
    QHeaderView,
)
from PyQt6.QtCore import pyqtSignal

from app.domain.dto import ProjectStats
from app.ui.models_qt import ProjectListModel
from app.ui.dialogs import CreateProjectDialog, show_error, show_info
from app.services.project_service import ProjectService
from app.services.db_service import DBService

logger = logging.getLogger(__name__)


class ProjectDashboard(QWidget):
    """Dashboard showing all projects."""

    project_selected = pyqtSignal(int)  # Emits project_id
    verification_requested = pyqtSignal()  # Emits when verification button clicked

    def __init__(self):
        super().__init__()
        self.project_service = ProjectService()
        self.init_ui()
        self.load_projects()

    def init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout()

        # Header
        header_layout = QHBoxLayout()
        title = QLabel("HDLE Premium - Projects")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        header_layout.addWidget(title)
        header_layout.addStretch()

        # Verification button (P1 Premium)
        verification_btn = QPushButton("🔍 P1 Verification")
        verification_btn.setToolTip("Open P1 Scenario 7 verification panel (Ctrl+Shift+V)")
        verification_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                font-weight: bold;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        verification_btn.clicked.connect(self.on_open_verification)
        header_layout.addWidget(verification_btn)

        create_btn = QPushButton("Create Project")
        create_btn.clicked.connect(self.on_create_project)
        header_layout.addWidget(create_btn)

        self.delete_btn = QPushButton("Delete Project")
        self.delete_btn.clicked.connect(self.on_delete_project)
        self.delete_btn.setEnabled(False)  # Disabled until selection
        self.delete_btn.setStyleSheet("QPushButton { color: #d32f2f; }")  # Red text
        header_layout.addWidget(self.delete_btn)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.load_projects)
        header_layout.addWidget(refresh_btn)

        layout.addLayout(header_layout)

        # My Projects section
        my_projects_label = QLabel("My Projects")
        my_projects_label.setStyleSheet("font-size: 14px; font-weight: bold; margin-top: 10px;")
        layout.addWidget(my_projects_label)

        self.project_model = ProjectListModel()
        self.project_table = QTableView()
        self.project_table.setModel(self.project_model)
        self.project_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.project_table.doubleClicked.connect(self.on_project_double_clicked)
        self.project_table.selectionModel().selectionChanged.connect(self.on_selection_changed)

        # Auto-resize columns
        header = self.project_table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        layout.addWidget(self.project_table)

        # Reference Corpora section
        ref_corpora_label = QLabel("Reference Corpora")
        ref_corpora_label.setStyleSheet("font-size: 14px; font-weight: bold; margin-top: 10px;")
        layout.addWidget(ref_corpora_label)

        self.ref_corpus_model = ProjectListModel()
        self.ref_corpus_table = QTableView()
        self.ref_corpus_table.setModel(self.ref_corpus_model)
        self.ref_corpus_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.ref_corpus_table.doubleClicked.connect(self.on_ref_corpus_double_clicked)
        self.ref_corpus_table.selectionModel().selectionChanged.connect(self.on_ref_selection_changed)

        # Auto-resize columns
        ref_header = self.ref_corpus_table.horizontalHeader()
        ref_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        layout.addWidget(self.ref_corpus_table)

        # Status bar
        self.status_label = QLabel("No projects")
        layout.addWidget(self.status_label)

        self.setLayout(layout)

    def load_projects(self):
        """Load and display projects."""
        try:
            with self.project_service.db_service.get_session() as session:
                projects = self.project_service.list_projects(session)

                # Convert to ProjectStats
                project_stats = []
                for p in projects:
                    # For M1, we don't have documents yet, so all counts are 0
                    stats = ProjectStats(
                        project_id=p.project_id,
                        name=p.name,
                        total_docs=0,
                        processed_docs=0,
                        total_lemmas=0,
                        total_ngrams=0,
                        is_general_corpus=bool(p.is_general_corpus),
                    )
                    project_stats.append(stats)

                # Split projects into two groups
                my_projects = [p for p in project_stats if not p.is_general_corpus]
                ref_corpora = [p for p in project_stats if p.is_general_corpus]

                self.project_model.update_projects(my_projects)
                self.ref_corpus_model.update_projects(ref_corpora)

                # Update status
                my_count = len(my_projects)
                ref_count = len(ref_corpora)
                if my_count + ref_count > 0:
                    self.status_label.setText(
                        f"My Projects: {my_count} | Reference Corpora: {ref_count}"
                    )
                else:
                    self.status_label.setText("No projects. Click 'Create Project' to get started.")

        except Exception as e:
            logger.exception("Failed to load projects")
            show_error(self, "Error", f"Failed to load projects: {e}")

    def on_create_project(self):
        """Handle create project button."""
        dialog = CreateProjectDialog(self)
        if dialog.exec():
            data = dialog.get_data()
            if not data["name"]:
                show_error(self, "Error", "Project name is required")
                return

            try:
                with self.project_service.db_service.get_session() as session:
                    project = self.project_service.create_project(
                        session,
                        name=data["name"],
                        description=data["description"],
                    )
                    logger.info(f"Created project: {project.name}")

                self.load_projects()

            except Exception as e:
                logger.exception("Failed to create project")
                show_error(self, "Error", f"Failed to create project: {e}")

    def on_project_double_clicked(self, index):
        """Handle project double-click."""
        if index.isValid():
            row = index.row()
            if row < len(self.project_model.projects):
                project_id = self.project_model.projects[row].project_id
                logger.info(f"Opening project: {project_id}")
                self.project_selected.emit(project_id)

    def on_selection_changed(self):
        """Handle selection change - enable/disable Delete button."""
        selected_indexes = self.project_table.selectedIndexes()
        self.delete_btn.setEnabled(len(selected_indexes) > 0)

        # Clear selection in Reference Corpora table
        if len(selected_indexes) > 0:
            self.ref_corpus_table.clearSelection()

    def on_open_verification(self):
        """Handle verification button click."""
        logger.info("Verification button clicked")
        self.verification_requested.emit()

    def on_delete_project(self):
        """Handle delete project button."""
        selected_indexes = self.project_table.selectedIndexes()
        if not selected_indexes:
            return

        row = selected_indexes[0].row()
        if row >= len(self.project_model.projects):
            return

        project = self.project_model.projects[row]

        # Block deletion of reference corpus
        if project.is_general_corpus:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self,
                "Cannot Delete Reference Corpus",
                f"'{project.name}' is a reference corpus (read-only).\n\n"
                f"Reference corpora cannot be deleted because they are used "
                f"for termhood calculations in other projects.\n\n"
                f"You can still:\n"
                f"✓ Open and browse documents\n"
                f"✓ Add/edit translations\n"
                f"✓ Extract terms\n\n"
                f"To remove this corpus, first unmark it as reference "
                f"(set is_general_corpus=0 in database).",
                QMessageBox.StandardButton.Ok
            )
            return

        # Confirmation dialog
        from PyQt6.QtWidgets import QMessageBox

        reply = QMessageBox.warning(
            self,
            "Delete Project",
            f"Are you sure you want to delete project '{project.name}'?\n\n"
            f"This will permanently delete:\n"
            f"- All documents ({project.total_docs})\n"
            f"- All lemmas ({project.total_lemmas})\n"
            f"- All n-grams ({project.total_ngrams})\n"
            f"- All statistics and analysis\n\n"
            f"This action cannot be undone!",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,  # Default to No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Perform deletion
        try:
            with self.project_service.db_service.get_session() as session:
                report = self.project_service.delete_project(session, project.project_id)

                if report.success:
                    # Show success message
                    show_info(
                        self,
                        "Project Deleted",
                        f"Project '{report.project_name}' deleted successfully.\n\n"
                        f"Removed:\n"
                        f"- {report.corpora_deleted} corpora\n"
                        f"- {report.documents_deleted} documents\n"
                        f"- {report.sentences_deleted} sentences\n"
                        f"- {report.lemmas_deleted} lemmas\n"
                        f"- {report.ngrams_deleted} n-grams\n"
                        f"- {report.term_cards_deleted} term cards",
                    )

                    # Refresh project list
                    self.load_projects()

                else:
                    show_error(
                        self,
                        "Deletion Failed",
                        f"Failed to delete project: {report.error_message}",
                    )

        except Exception as e:
            logger.exception("Failed to delete project")
            show_error(
                self,
                "Error",
                f"An error occurred while deleting the project:\n\n{str(e)[:200]}",
            )

    def on_ref_corpus_double_clicked(self, index):
        """Handle reference corpus double-click."""
        if index.isValid():
            row = index.row()
            if row < len(self.ref_corpus_model.projects):
                project_id = self.ref_corpus_model.projects[row].project_id
                logger.info(f"Opening reference corpus: {project_id}")
                self.project_selected.emit(project_id)

    def on_ref_selection_changed(self):
        """Handle reference corpus selection change."""
        # Disable delete button for reference corpora (always read-only)
        self.delete_btn.setEnabled(False)

        # Clear selection in My Projects table
        self.project_table.clearSelection()
