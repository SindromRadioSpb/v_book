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
from app.ui.terms_view import TermsView
from app.ui.concordance_view import ConcordanceView
from app.ui.term_card_view import TermCardView
from app.ui.user_dictionaries_view import UserDictionariesView
from app.ui.export_view import ExportView
from app.ui.sentences_view import SentencesView
from app.services.project_service import ProjectService

logger = logging.getLogger(__name__)


class ProjectView(QWidget):
    """Main project workspace."""

    back_to_dashboard = pyqtSignal()
    open_translation_management_requested = pyqtSignal(int)

    def __init__(self, project_id: int):
        super().__init__()
        self.project_id = project_id
        self.project_name = ""
        self.project_created_at = ""
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

        # Terms tab (M5: MWE + Clustering)
        self.terms_view = TermsView(self.project_id)
        self.tabs.addTab(self.terms_view, "Terms")

        # Concordance tab (M6)
        self.concordance_view = ConcordanceView(self.project_id)
        self.tabs.addTab(self.concordance_view, "Concordance")

        # Connect concordance navigation to documents view
        self.concordance_view.navigate_to_document.connect(self.on_navigate_to_document)

        # Term Cards tab
        self.term_card_view = TermCardView(self.project_id)
        self.tabs.addTab(self.term_card_view, "Term Cards")

        # User Dictionaries tab (P0)
        self.user_dictionaries_view = UserDictionariesView(self.project_id)
        self.user_dictionaries_view.open_translation_management_requested.connect(
            self.on_open_translation_management
        )
        self.tabs.addTab(self.user_dictionaries_view, "User Dictionaries")

        # Sentences workspace tab (Task 22)
        self.sentences_view = SentencesView(self.project_id)
        self.tabs.addTab(self.sentences_view, "Sentences")
        # Refresh sentences after NLP processing completes
        self.documents_view.processing_completed.connect(self.sentences_view._reload)

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
                    self.project_name = str(project.name or "")
                    self.project_created_at = str(getattr(project, "created_at", "") or "")
                    # Add 🌐 marker for reference corpus projects
                    if project.is_general_corpus:
                        self.project_title.setText(f"Project: 🌐 {project.name}")
                    else:
                        self.project_title.setText(f"Project: {project.name}")
                else:
                    self.project_name = ""
                    self.project_created_at = ""
                    self.project_title.setText("Project not found")
        except Exception as e:
            logger.exception("Failed to load project")
            self.project_name = ""
            self.project_created_at = ""
            self.project_title.setText("Error loading project")

    def on_back_clicked(self):
        """Handle back button."""
        self.back_to_dashboard.emit()

    def focus_tab(self, tab_key: str) -> bool:
        """Focus project tab by stable key.

        Supported keys:
        - documents
        - sentences
        - dictionary
        - terms
        - term_cards
        - export
        """
        key = str(tab_key or "").strip().lower()
        mapping = {
            "documents": self.documents_view,
            "sentences": self.sentences_view,
            "dictionary": self.dictionary_view,
            "terms": self.terms_view,
            "term_cards": self.term_card_view,
            "export": self.export_view,
        }
        target = mapping.get(key)
        if target is None:
            return False
        self.tabs.setCurrentWidget(target)
        return True

    def on_navigate_to_document(self, doc_id: int, sentence_id: int):
        """
        Navigate to a specific document from concordance results (M6).

        Args:
            doc_id: Document ID to show
            sentence_id: Sentence ID to highlight
        """
        logger.info(f"Navigating to document {doc_id}, sentence {sentence_id}")

        # Switch to Documents tab
        self.tabs.setCurrentWidget(self.documents_view)

        # Highlight the document
        self.documents_view.highlight_document(doc_id, sentence_id)

    def on_open_translation_management(self):
        """Route User Dictionaries deep-link to app-level TM panel."""
        self.open_translation_management_requested.emit(self.project_id)
