"""Project dashboard - main landing page."""

import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QProgressDialog,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from app.domain.dto import ProjectStats
from app.services.project_service import ProjectService
from app.ui.dialogs import CreateProjectDialog, show_error, show_info
from app.ui.dialogs.project_artifact_governance_dialog import (
    ProjectArtifactGovernanceDialog,
)
from app.ui.models_qt import ProjectListModel
from app.ui.workers import ProjectDeleteWorker

logger = logging.getLogger(__name__)


class ProjectDashboard(QWidget):
    """Dashboard showing all projects."""

    project_selected = pyqtSignal(int)  # Emits project_id
    verification_requested = pyqtSignal()  # Emits when verification button clicked
    projects_loaded = pyqtSignal(list)  # Emits list[dict] for sidebar search catalog
    project_deleted = pyqtSignal(int)  # Emits deleted project_id after successful deletion

    def __init__(self):
        super().__init__()
        self.project_service = ProjectService()
        self._delete_worker: ProjectDeleteWorker | None = None
        self._delete_progress: QProgressDialog | None = None
        self._governance_dialog: ProjectArtifactGovernanceDialog | None = None
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
        verification_btn.setStyleSheet(
            """
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
        """
        )
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

        self.governance_btn = QPushButton("Data Governance")
        self.governance_btn.clicked.connect(self.on_open_governance)
        self.governance_btn.setEnabled(False)
        header_layout.addWidget(self.governance_btn)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.load_projects)
        header_layout.addWidget(refresh_btn)

        layout.addLayout(header_layout)

        # Projects table (includes both regular and reference corpus projects)
        self.project_model = ProjectListModel()
        self.project_table = QTableView()
        self.project_table.setModel(self.project_model)
        self.project_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.project_table.doubleClicked.connect(self.on_project_double_clicked)
        self.project_table.selectionModel().selectionChanged.connect(self.on_selection_changed)

        # Enable F2 editing (NOT double-click to avoid conflict with open-project)
        self.project_table.setEditTriggers(QTableView.EditTrigger.EditKeyPressed)

        # Install event filter for F2 key
        self.project_table.installEventFilter(self)

        # Connect dataChanged to save handler
        self.project_model.dataChanged.connect(self.on_project_renamed)

        # Context menu
        self.project_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.project_table.customContextMenuRequested.connect(self.show_context_menu)

        # Auto-resize columns
        header = self.project_table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        layout.addWidget(self.project_table)

        # Status bar
        self.status_label = QLabel("No projects")
        layout.addWidget(self.status_label)

        self.setLayout(layout)

    def load_projects(self):
        """Load and display projects."""
        try:
            with self.project_service.db_service.get_session() as session:
                projects = self.project_service.list_projects(session)

                # Convert to ProjectStats with REAL metrics
                project_stats = []
                for p in projects:
                    # Get real statistics from database
                    project_metrics = self.project_service.get_project_stats(session, p.project_id)

                    stats = ProjectStats(
                        project_id=p.project_id,
                        name=p.name,
                        total_docs=project_metrics["total_docs"],
                        processed_docs=project_metrics["processed_docs"],
                        total_lemmas=project_metrics["total_lemmas"],
                        total_ngrams=project_metrics["total_ngrams"],
                        is_general_corpus=bool(p.is_general_corpus),
                    )
                    project_stats.append(stats)

                # Show all projects in one list (including reference corpora)
                self.project_model.update_projects(project_stats)

                # Update status
                my_count = len([p for p in project_stats if not p.is_general_corpus])
                ref_count = len([p for p in project_stats if p.is_general_corpus])

                if project_stats:
                    if ref_count > 0:
                        self.status_label.setText(
                            f"Total projects: {len(project_stats)} (My Projects: {my_count} | Reference Corpora: {ref_count})"
                        )
                    else:
                        self.status_label.setText(f"Total projects: {len(project_stats)}")
                else:
                    self.status_label.setText("No projects. Click 'Create Project' to get started.")

                # Emit project catalog for workspace sidebar search/recent section.
                self.projects_loaded.emit(
                    [{"project_id": int(p.project_id), "name": str(p.name)} for p in project_stats]
                )

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
        has_selection = len(selected_indexes) > 0
        self.delete_btn.setEnabled(has_selection)
        self.governance_btn.setEnabled(has_selection)

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
                QMessageBox.StandardButton.Ok,
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

        self._start_delete_worker(project.project_id)

    def _start_delete_worker(self, project_id: int) -> None:
        if self._delete_worker and self._delete_worker.isRunning():
            return

        self.delete_btn.setEnabled(False)
        self._delete_progress = QProgressDialog("Deleting project...", "", 0, 0, self)
        self._delete_progress.setWindowTitle("Delete Project")
        self._delete_progress.setCancelButton(None)
        self._delete_progress.setModal(True)
        self._delete_progress.setMinimumDuration(0)
        self._delete_progress.show()

        worker = ProjectDeleteWorker(project_id=project_id)
        self._delete_worker = worker
        worker.status.connect(self._on_delete_status)
        worker.finished.connect(self._on_delete_finished)
        worker.error.connect(self._on_delete_error)
        worker.start()

    def _on_delete_status(self, message: str) -> None:
        self.status_label.setText(message)
        if self._delete_progress:
            self._delete_progress.setLabelText(message)

    def _on_delete_finished(self, report) -> None:
        self._cleanup_delete_worker()

        if report.success:
            deleted_project_id = getattr(report, "project_id", None)
            if deleted_project_id is not None:
                try:
                    self.project_deleted.emit(int(deleted_project_id))
                except (TypeError, ValueError):
                    logger.warning(
                        "Delete report contains invalid project_id: %r", deleted_project_id
                    )
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
            self.load_projects()
            self.status_label.setText("Project deleted")
            return

        show_error(
            self,
            "Deletion Failed",
            f"Failed to delete project: {report.error_message}",
        )
        self.status_label.setText("Delete failed")

    def _on_delete_error(self, error_message: str) -> None:
        self._cleanup_delete_worker()
        logger.error("Delete worker failed: %s", error_message, exc_info=True)
        show_error(
            self,
            "Error",
            f"An error occurred while deleting the project:\n\n{error_message[:200]}",
        )
        self.status_label.setText("Delete failed")

    def _cleanup_delete_worker(self) -> None:
        if self._delete_progress:
            self._delete_progress.close()
            self._delete_progress.deleteLater()
            self._delete_progress = None

        if self._delete_worker:
            self._delete_worker.deleteLater()
            self._delete_worker = None

        self.on_selection_changed()

    def eventFilter(self, obj, event):
        """Handle F2 key to start editing Name column."""
        if obj == self.project_table and event.type() == event.Type.KeyPress:
            from PyQt6.QtGui import QKeyEvent

            if isinstance(event, QKeyEvent) and event.key() == Qt.Key.Key_F2:
                # Get current selection
                current_index = self.project_table.currentIndex()
                if current_index.isValid():
                    # Jump to Name column (column 1)
                    name_index = self.project_model.index(current_index.row(), 1)
                    self.project_table.setCurrentIndex(name_index)
                    self.project_table.edit(name_index)
                    return True  # Event handled

        return super().eventFilter(obj, event)

    def on_project_renamed(self, top_left, bottom_right, roles):
        """Handle inline edit of project name - save to database."""
        # Check if Name column was edited (col 1)
        if top_left.column() != 1:
            return

        row = top_left.row()
        project = self.project_model.projects[row]

        # Get new name
        new_name = project.name

        # Validate and save
        try:
            with self.project_service.db_service.get_session() as session:
                # Save via service (includes validation and audit)
                updated_project = self.project_service.rename_project(
                    session, project.project_id, new_name
                )

                logger.info(f"Renamed project {project.project_id} to '{new_name}'")

                # Refresh project list to show updated name everywhere
                self.load_projects()

        except ValueError as e:
            # Validation error - revert and show error
            logger.warning(f"Project rename validation failed: {e}")
            show_error(self, "Rename Failed", str(e))
            # Revert by reloading
            self.load_projects()
        except Exception as e:
            # Other error - revert and show error
            logger.exception("Failed to rename project")
            show_error(self, "Rename Failed", f"Failed to rename project: {e}")
            # Revert by reloading
            self.load_projects()

    def show_context_menu(self, pos):
        """Show context menu with Rename, governance, and Delete options."""
        # Get selected row
        index = self.project_table.indexAt(pos)
        if not index.isValid():
            return

        row = index.row()
        if row >= len(self.project_model.projects):
            return

        project = self.project_model.projects[row]

        # Create menu
        menu = QMenu(self)

        # Rename action
        rename_action = menu.addAction("Rename (F2)")
        rename_action.triggered.connect(lambda: self.start_rename(row))

        menu.addSeparator()

        governance_action = menu.addAction("Derived Data Governance...")
        governance_action.triggered.connect(
            lambda checked=False, project_id=project.project_id, name=project.name: (
                self._open_governance_dialog(int(project_id), str(name))
            )
        )

        menu.addSeparator()

        # Delete action (existing functionality, grayed out for reference corpus)
        delete_action = menu.addAction("Delete")
        delete_action.triggered.connect(self.on_delete_project)
        if project.is_general_corpus:
            delete_action.setEnabled(False)
            delete_action.setToolTip("Cannot delete reference corpus")

        # Show menu
        menu.exec(self.project_table.viewport().mapToGlobal(pos))

    def start_rename(self, row):
        """Start editing the Name column for a specific row."""
        name_index = self.project_model.index(row, 1)
        self.project_table.setCurrentIndex(name_index)
        self.project_table.edit(name_index)

    def _get_selected_project(self) -> ProjectStats | None:
        selected_indexes = self.project_table.selectedIndexes()
        if not selected_indexes:
            return None
        row = selected_indexes[0].row()
        if row < 0 or row >= len(self.project_model.projects):
            return None
        return self.project_model.projects[row]

    def on_open_governance(self) -> None:
        project = self._get_selected_project()
        if project is None:
            return
        self._open_governance_dialog(int(project.project_id), str(project.name))

    def _open_governance_dialog(self, project_id: int, project_name: str) -> None:
        dialog = self.__dict__.get("_governance_dialog")
        if dialog is not None and getattr(dialog, "project_id", None) == int(project_id):
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
            return

        if dialog is not None:
            dialog.close()

        dialog = ProjectArtifactGovernanceDialog(int(project_id), str(project_name), self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.destroyed.connect(lambda *_args: setattr(self, "_governance_dialog", None))
        self._governance_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
