"""Concordance view - KWIC search (M6)."""
import logging
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel

logger = logging.getLogger(__name__)


class ConcordanceView(QWidget):
    """Concordance/KWIC search view."""

    def __init__(self, project_id: int):
        super().__init__()
        self.project_id = project_id
        self.init_ui()

    def init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout()

        info = QLabel(
            "Concordance View\n\n"
            "This tab will provide:\n"
            "• Full-text search across all documents\n"
            "• KWIC (Key Word In Context) display\n"
            "• FTS5-powered fast search\n"
            "• Navigation to source documents\n\n"
            "To be implemented in M6"
        )
        info.setStyleSheet("padding: 20px; font-size: 14px;")
        layout.addWidget(info)
        layout.addStretch()

        self.setLayout(layout)
