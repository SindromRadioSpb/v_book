"""Project view - main workspace for a project."""
import logging
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTabWidget,
    QPushButton,
    QLabel,
)
from PyQt6.QtCore import pyqtSignal

from app.ui.documents_view import DocumentsView
from app.ui.dictionary_view import DictionaryView
from app.ui.concordance_view import ConcordanceView
from app.ui.term_card_view import TermCardView
from app.ui.export_view import ExportView
from app.services.project_service import ProjectService

logger = logging.getLogger(__name__)


class ProjectView(QWidget):
    """Main project workspace."""

    back_to_dashboard = pyqtSignal()

    def __init__(self, project_id: int):
        super().__init__()
        self.project_id = project_id
        self.project_service = ProjectService()
        self.init_ui()
        self.load_project()

    def init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout()

        # Header
        header_layout = QHBoxLayout()

        back_btn = QPushButton("← Back to Projects")
        back_btn.clicked.connect(self.on_back_clicked)
        header_layout.addWidget(back_btn)

        self.project_title = QLabel("Loading...")
        self.project_title.setStyleSheet("font-size: 16px; font-weight: bold;")
        header_layout.addWidget(self.project_title)
        header_layout.addStretch()

        layout.addLayout(header_layout)

        # Tab widget
        self.tabs = QTabWidget()

        # Documents tab (M2)
        self.documents_view = DocumentsView(self.project_id)
        self.tabs.addTab(self.documents_view, "Documents")

        # Dictionary tab
        self.dictionary_view = DictionaryView(self.project_id)
        self.tabs.addTab(self.dictionary_view, "Dictionary")

        # Connect signals: when processing completes, refresh dictionary
        self.documents_view.processing_completed.connect(self.dictionary_view.refresh)

        # MWE tab (M5)
        mwe_placeholder = QLabel("MWE/Collocations tab (to be implemented in M5)")
        mwe_placeholder.setStyleSheet("padding: 20px;")
        self.tabs.addTab(mwe_placeholder, "MWE")

        # Concordance tab
        self.concordance_view = ConcordanceView(self.project_id)
        self.tabs.addTab(self.concordance_view, "Concordance")

        # Term Cards tab
        self.term_card_view = TermCardView(self.project_id)
        self.tabs.addTab(self.term_card_view, "Term Cards")

        # Export tab
        self.export_view = ExportView(self.project_id)
        self.tabs.addTab(self.export_view, "Export")

        layout.addWidget(self.tabs)

        self.setLayout(layout)

    def load_project(self):
        """Load project details."""
        try:
            with self.project_service.db_service.get_session() as session:
                project = self.project_service.get_project(session, self.project_id)
                if project:
                    self.project_title.setText(f"Project: {project.name}")
                else:
                    self.project_title.setText("Project not found")
        except Exception as e:
            logger.exception("Failed to load project")
            self.project_title.setText("Error loading project")

    def on_back_clicked(self):
        """Handle back button."""
        self.back_to_dashboard.emit()
