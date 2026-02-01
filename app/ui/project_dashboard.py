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
from app.ui.dialogs import CreateProjectDialog, show_error
from app.services.project_service import ProjectService
from app.services.db_service import DBService

logger = logging.getLogger(__name__)


class ProjectDashboard(QWidget):
    """Dashboard showing all projects."""

    project_selected = pyqtSignal(int)  # Emits project_id

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

        create_btn = QPushButton("Create Project")
        create_btn.clicked.connect(self.on_create_project)
        header_layout.addWidget(create_btn)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.load_projects)
        header_layout.addWidget(refresh_btn)

        layout.addLayout(header_layout)

        # Project table
        self.project_model = ProjectListModel()
        self.project_table = QTableView()
        self.project_table.setModel(self.project_model)
        self.project_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.project_table.doubleClicked.connect(self.on_project_double_clicked)

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
                    )
                    project_stats.append(stats)

                self.project_model.update_projects(project_stats)

                if project_stats:
                    self.status_label.setText(f"Total projects: {len(project_stats)}")
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
