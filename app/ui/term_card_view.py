"""Term card view - curation workflow (M8)."""
import logging
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel

logger = logging.getLogger(__name__)


class TermCardView(QWidget):
    """Term card curation view."""

    def __init__(self, project_id: int):
        super().__init__()
        self.project_id = project_id
        self.init_ui()

    def init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout()

        info = QLabel(
            "Term Cards View\n\n"
            "This tab will provide:\n"
            "• Term-by-term review workflow\n"
            "• Approve/Reject/Needs Review status\n"
            "• Add aliases and stopwords\n"
            "• Pin translations and examples\n"
            "• Quality scoring\n\n"
            "To be implemented in M8"
        )
        info.setStyleSheet("padding: 20px; font-size: 14px;")
        layout.addWidget(info)
        layout.addStretch()

        self.setLayout(layout)
