"""Dictionary view - lemmas and MWE list (M3+)."""
import logging
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel

logger = logging.getLogger(__name__)


class DictionaryView(QWidget):
    """Dictionary view showing lemmas and n-grams."""

    def __init__(self, project_id: int):
        super().__init__()
        self.project_id = project_id
        self.init_ui()

    def init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout()

        info = QLabel(
            "Dictionary View\n\n"
            "This tab will display:\n"
            "• Top lemmas by frequency\n"
            "• Multi-word expressions (MWE)\n"
            "• Filters: Top-N, min frequency, POS patterns\n"
            "• Translations\n"
            "• Moderation status\n\n"
            "To be implemented in M3+M5"
        )
        info.setStyleSheet("padding: 20px; font-size: 14px;")
        layout.addWidget(info)
        layout.addStretch()

        self.setLayout(layout)
