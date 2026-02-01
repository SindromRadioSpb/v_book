"""Export view - export to various formats (M9)."""
import logging
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel

logger = logging.getLogger(__name__)


class ExportView(QWidget):
    """Export view for various formats."""

    def __init__(self, project_id: int):
        super().__init__()
        self.project_id = project_id
        self.init_ui()

    def init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout()

        info = QLabel(
            "Export Center\n\n"
            "This tab will provide export to:\n"
            "• Excel (Statistics + Dictionary sheets)\n"
            "• CSV/TSV/JSONL\n"
            "• TBX (TermBase eXchange)\n"
            "• TMX (Translation Memory eXchange)\n"
            "• Configurable filters and presets\n\n"
            "To be implemented in M9"
        )
        info.setStyleSheet("padding: 20px; font-size: 14px;")
        layout.addWidget(info)
        layout.addStretch()

        self.setLayout(layout)
